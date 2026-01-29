"""
Command-line interface for the DevRel Research Agent.
"""

import argparse
import sys
import json
import threading
import time
import re
import os
from datetime import datetime
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from agent import get_agent
from config import config
from utils.logging_utils import setup_logging, get_logger
from exceptions import DevRelResearchError
from tools.elasticsearch_tools import store_discovery

# Setup logging
setup_logging()
logger = get_logger(__name__)


@dataclass
class ProgressTracker:
    """Track and display progress of agent operations."""

    # Step definitions with display names and emoji
    STEPS = {
        "metrics": ("metrics-agent", "📊 Fetching GitHub metrics", "📊"),
        "sentiment": ("sentiment-agent", "💬 Analyzing sentiment", "💬"),
        "web": ("web-research-agent", "🌐 Researching adoption", "🌐"),
        "elastic": ("elastic-agent", "🔍 Querying Elasticsearch", "🔍"),
        "scoring": ("orchestrator", "📈 Calculating viability", "📈"),
        "report": ("orchestrator", "📝 Generating report", "📝"),
        "storage": ("orchestrator", "💾 Storing results", "💾"),
    }

    completed: list = field(default_factory=list)
    current_step: Optional[str] = None
    current_detail: str = ""
    stop_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    verbose: bool = False  # Show all activity in real-time
    activity_log: list = field(default_factory=list)  # Log of all activities

    # Log patterns to detect activity
    PATTERNS = [
        # Metrics agent patterns
        (
            r"Fetching fresh metrics for (.+)",
            "metrics",
            "🔄 Fetching fresh metrics for {0}",
        ),
        (
            r"Fetching metrics from web for (.+)",
            "metrics",
            "🌐 Fetching metrics from web for {0}",
        ),
        (r"GitHub cache HIT for (.+)", "metrics", "⚡ Using cached metrics for {0}"),
        (r"Successfully fetched metrics for (.+)", "metrics", "✅ Got metrics for {0}"),
        # Sentiment agent patterns
        (
            r"Fetching (\d+) recent issues for (.+)",
            "sentiment",
            "📋 Fetching {0} issues for {1}",
        ),
        (r"Fetched (\d+) issues for (.+)", "sentiment", "✅ Got {0} issues for {1}"),
        (
            r"Fetching (\d+) discussions for (.+)",
            "sentiment",
            "💬 Fetching {0} discussions for {1}",
        ),
        (
            r"Fetched (\d+) discussions for (.+)",
            "sentiment",
            "✅ Got {0} discussions for {1}",
        ),
        # Web agent patterns
        (r"Searching Tavily for: (.+)", "web", "🔎 Searching: {0}"),
        (r"Found (\d+) results for query: (.+)", "web", "✅ Found {0} results"),
        (r"Cache HIT for query: (.+)", "web", "⚡ Using cached: {0}"),
        (r"Cache MISS for query: (.+)", "web", "🔄 Searching: {0}"),
        (r"Cached search results for: (.+)", "web", "💾 Cached results"),
        # Elastic agent patterns
        (
            r"Semantic search found (\d+) results",
            "elastic",
            "🔍 Found {0} similar technologies",
        ),
        (r"Invoking Elastic agent tool: (.+)", "elastic", "🔧 Running: {0}"),
        # Storage patterns
        (
            r"Stored timeseries snapshot for (.+)",
            "storage",
            "📊 Stored timeseries for {0}",
        ),
        (r"Stored (.+) signal for (.+)", "storage", "💾 Recorded {0} signal"),
        (r"Stored research report for (.+)", "storage", "📄 Saved report for {0}"),
        (r"Stored snapshot for (.+)", "storage", "💾 Saved snapshot for {0}"),
        # Scoring patterns
        (r"calculate_viability_score", "scoring", "📈 Calculating viability score"),
        (
            r"Storing research snapshot for (.+)",
            "storage",
            "💾 Storing snapshot for {0}",
        ),
        # API calls
        (
            r"HTTP Request: POST https://api.anthropic.com",
            "orchestrator",
            "🤖 AI processing...",
        ),
        (r"HTTP Request: POST https://api.github.com", "metrics", "🐙 GitHub API call"),
    ]

    def update_from_log_line(self, line: str):
        """Parse a log line and update progress state."""
        with self.lock:
            for pattern, step, detail_fmt in self.PATTERNS:
                match = re.search(pattern, line)
                if match:
                    # Mark previous step as completed if moving to new step
                    if self.current_step and self.current_step != step:
                        if self.current_step not in self.completed:
                            self.completed.append(self.current_step)

                    self.current_step = step
                    try:
                        detail = detail_fmt.format(*match.groups())
                        self.current_detail = detail[:60]

                        # Add to activity log for verbose mode
                        if self.verbose:
                            timestamp = datetime.now().strftime("%H:%M:%S")
                            agent_name = self.STEPS.get(step, (step, "", ""))[0]
                            self.activity_log.append((timestamp, agent_name, detail))
                    except (IndexError, KeyError):
                        self.current_detail = detail_fmt
                    break

    def mark_complete(self, step: str):
        """Mark a step as completed."""
        with self.lock:
            if step not in self.completed:
                self.completed.append(step)

    def get_display(self) -> str:
        """Generate the progress display string."""
        with self.lock:
            lines = []

            # Current activity with spinner
            if self.current_step and self.current_step in self.STEPS:
                agent_name, _, emoji = self.STEPS[self.current_step]
                lines.append(f"  {emoji} {agent_name}: {self.current_detail}")

            # Completed steps
            if self.completed:
                completed_names = []
                for step in self.completed:
                    if step in self.STEPS:
                        completed_names.append(self.STEPS[step][0])
                if completed_names:
                    lines.append(f"  ✅ Completed: {', '.join(completed_names)}")

            # Pending steps
            pending = [
                s
                for s in ["metrics", "sentiment", "web", "scoring"]
                if s not in self.completed and s != self.current_step
            ]
            if pending:
                pending_names = [self.STEPS[s][0] for s in pending if s in self.STEPS]
                if pending_names:
                    lines.append(f"  ⏳ Pending: {', '.join(pending_names)}")

            return "\n".join(lines) if lines else ""


class ProgressDisplay:
    """Manages the progress display with spinner and status updates."""

    def __init__(self, title: str, verbose: bool = False):
        self.title = title
        self.verbose = verbose
        self.tracker = ProgressTracker(verbose=verbose)
        self.stop_event = threading.Event()
        self.display_thread = None
        self.log_thread = None
        self.log_file = config.LOG_FILE
        self.last_log_pos = 0
        self.last_activity_count = 0

    def _watch_logs(self):
        """Background thread to watch log file for updates."""
        # Get initial file position
        if os.path.exists(self.log_file):
            with open(self.log_file, "r") as f:
                f.seek(0, 2)  # Seek to end
                self.last_log_pos = f.tell()

        while not self.stop_event.is_set():
            try:
                if os.path.exists(self.log_file):
                    with open(self.log_file, "r") as f:
                        f.seek(self.last_log_pos)
                        new_lines = f.readlines()
                        self.last_log_pos = f.tell()

                        for line in new_lines:
                            self.tracker.update_from_log_line(line)
            except Exception:
                pass
            time.sleep(0.1)

    def _display_loop(self):
        """Background thread to update the display."""
        spinner_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        idx = 0
        last_display = ""

        while not self.stop_event.is_set():
            # Build display
            spinner = spinner_chars[idx]
            idx = (idx + 1) % len(spinner_chars)

            if self.verbose:
                # Verbose mode: print new activities as they happen
                with self.tracker.lock:
                    new_activities = self.tracker.activity_log[
                        self.last_activity_count :
                    ]
                    self.last_activity_count = len(self.tracker.activity_log)

                for timestamp, agent, detail in new_activities:
                    # Print each activity on its own line
                    print(f"  [{timestamp}] {agent}: {detail}", flush=True)

                # Just show spinner on current line
                sys.stdout.write(f"\r{spinner} {self.title}...")
                sys.stdout.flush()
            else:
                # Compact mode: update in place
                progress = self.tracker.get_display()

                # Clear previous lines and print new status
                if last_display:
                    # Move up and clear previous lines
                    line_count = last_display.count("\n") + 1
                    sys.stdout.write(f"\033[{line_count}A\033[J")

                display = (
                    f"{spinner} {self.title}\n{progress}"
                    if progress
                    else f"{spinner} {self.title}"
                )
                print(display, flush=True)
                last_display = display

            time.sleep(0.1)

        # Final clear (only in compact mode)
        if not self.verbose and last_display:
            line_count = last_display.count("\n") + 1
            sys.stdout.write(f"\033[{line_count}A\033[J")
            sys.stdout.flush()

    def __enter__(self):
        self.stop_event.clear()
        self.log_thread = threading.Thread(target=self._watch_logs, daemon=True)
        self.display_thread = threading.Thread(target=self._display_loop, daemon=True)
        self.log_thread.start()
        self.display_thread.start()
        return self.tracker

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_event.set()
        if self.display_thread:
            self.display_thread.join(timeout=1)
        if self.log_thread:
            self.log_thread.join(timeout=1)

        # Print completion summary
        print()  # New line after spinner
        completed = self.tracker.completed
        if completed:
            agents = [self.tracker.STEPS.get(s, (s, "", ""))[0] for s in completed]
            print(f"✅ Completed: {', '.join(agents)}")

        # In verbose mode, print activity count
        if self.verbose:
            print(f"📊 Total activities tracked: {len(self.tracker.activity_log)}")


# Global verbose flag
_verbose_mode = False


def set_verbose_mode(verbose: bool):
    """Set global verbose mode."""
    global _verbose_mode
    _verbose_mode = verbose


@contextmanager
def spinner(message="Working", verbose: bool = None):
    """Spinner context manager with optional verbose mode."""
    # Use global verbose mode if not specified
    use_verbose = verbose if verbose is not None else _verbose_mode
    with ProgressDisplay(message, verbose=use_verbose) as tracker:
        yield tracker


# Directory for saving research reports
REPORTS_DIR = Path(__file__).parent / "research_reports"


def save_report_to_file(content: str, report_type: str, identifier: str) -> Path:
    """
    Save a research report to the research_reports directory.

    Args:
        content: The markdown report content
        report_type: Type of report ('evaluation' or 'comparison')
        identifier: Identifier for the report (repo name or comparison key)

    Returns:
        Path to the saved file
    """
    # Create directory if it doesn't exist
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # Clean identifier for filename (replace / with _)
    clean_id = identifier.replace("/", "_").replace(" ", "_")
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Generate filename
    filename = f"{report_type}_{clean_id}_{date_str}.md"
    filepath = REPORTS_DIR / filename

    # Add metadata header
    header = f"""---
type: {report_type}
subject: {identifier}
generated: {datetime.now().isoformat()}
---

"""

    # Write file
    with open(filepath, "w") as f:
        f.write(header + content)

    logger.info(f"Saved report to {filepath}")
    return filepath


def parse_discoveries(response: str) -> dict:
    """
    Parse the discovery response markdown to extract structured technology data.

    Args:
        response: The markdown response from the discovery agent

    Returns:
        Dictionary with:
            - technologies: List of discovered technologies
            - most_promising: Name of most promising technology
    """
    technologies = []
    most_promising = None

    # Pattern to match technology sections: ### 1. Name, ### 2. Name, etc.
    tech_pattern = r"###\s*\d+\.\s*([^\n]+)"
    tech_matches = re.findall(tech_pattern, response)

    for tech_name in tech_matches:
        tech_name = tech_name.strip()
        if not tech_name:
            continue

        tech_data = {"name": tech_name}

        # Find the section for this technology and extract fields
        # Look for content between this tech header and the next ### header
        section_pattern = rf"###\s*\d+\.\s*{re.escape(tech_name)}(.*?)(?=###|\Z)"
        section_match = re.search(section_pattern, response, re.DOTALL)

        if section_match:
            section = section_match.group(1)

            # Extract GitHub URL
            github_match = re.search(
                r"\*?\*?GitHub\*?\*?:\s*\[?([^\s\]\n]+)", section, re.IGNORECASE
            )
            if github_match:
                url = github_match.group(1).strip("[]()").rstrip(")")
                if "github.com" in url:
                    tech_data["github_url"] = url

            # Extract Website URL
            website_match = re.search(
                r"\*?\*?Website\*?\*?:\s*\[?([^\s\]\n]+)", section, re.IGNORECASE
            )
            if website_match:
                url = website_match.group(1).strip("[]()").rstrip(")")
                if url and url != "N/A" and "http" in url:
                    tech_data["website_url"] = url

            # Extract Description
            desc_match = re.search(
                r"\*?\*?Description\*?\*?:\s*([^\n]+)", section, re.IGNORECASE
            )
            if desc_match:
                tech_data["description"] = desc_match.group(1).strip()

            # Extract Relevance
            rel_match = re.search(
                r"\*?\*?Relevance\*?\*?:\s*([^\n]+)", section, re.IGNORECASE
            )
            if rel_match:
                tech_data["relevance"] = rel_match.group(1).strip()

            # Extract Stars/Popularity
            stars_match = re.search(
                r"(\d{1,3}(?:,\d{3})*|\d+)[kK]?\s*(?:stars|⭐)", section
            )
            if stars_match:
                stars_str = stars_match.group(1).replace(",", "")
                try:
                    stars = int(stars_str)
                    # Handle "K" suffix
                    if "k" in stars_match.group(0).lower() and stars < 1000:
                        stars *= 1000
                    tech_data["stars"] = stars
                except ValueError:
                    pass

        # Only add if we have at least a name and GitHub URL
        if tech_data.get("github_url") or tech_data.get("name"):
            technologies.append(tech_data)

    # Extract most promising technology
    promising_match = re.search(
        r"\*?\*?Most Promising\*?\*?:\s*\[?([^\n\]]+)", response, re.IGNORECASE
    )
    if promising_match:
        most_promising = promising_match.group(1).strip()
        # Clean up markdown formatting
        most_promising = re.sub(r"\*\*|\[|\]|\(.*\)", "", most_promising).strip()

    return {"technologies": technologies, "most_promising": most_promising}


def ask_command(args):
    """
    Handle natural language queries - let the LLM find and analyze repos.

    This is the most flexible command - users can ask questions like:
    - "What are the best Python web frameworks?"
    - "Compare the top 3 LLM orchestration libraries"
    - "Evaluate MongoDB vs PostgreSQL for real-time analytics"

    The LLM will identify relevant repositories and perform the analysis.
    """
    query = args.query

    logger.info(f"CLI: Natural language query: {query}")
    print(f"\n{'='*80}")
    print(f"Query: {query}")
    print(f"{'='*80}")
    print(f"\n💡 The agent will identify relevant repositories and analyze them.\n")

    # Enhance the query with instructions for the agent
    enhanced_query = f"""
{query}

INSTRUCTIONS:
1. First, identify the most relevant GitHub repositories for this query
2. Use web search if needed to find the best/most popular repos in this space
3. Then perform the appropriate analysis (evaluation, comparison, or discovery)
4. Include all repository links, metrics, and detailed analysis in your response

IMPORTANT - REPOSITORY SELECTION:
Use EXACT repository names. Common repositories:

DATABASES:
- MongoDB: "mongodb/mongo" (NOT mongodb/mongodb)
- Elasticsearch: "elastic/elasticsearch"
- PostgreSQL: "postgres/postgres"
- Redis: "redis/redis"
- MySQL: "mysql/mysql-server"

SEARCH/ANALYTICS:
- Meilisearch: "meilisearch/meilisearch"
- Typesense: "typesense/typesense" 
- OpenSearch: "opensearch-project/OpenSearch"

AI/ML FRAMEWORKS:
- LangChain: "langchain-ai/langchain"
- LlamaIndex: "run-llama/llama_index"
- Hugging Face: "huggingface/transformers"

WEB FRAMEWORKS:
- FastAPI: "tiangolo/fastapi"
- Flask: "pallets/flask"
- Django: "django/django"
- Express: "expressjs/express"

NOTE: If the GitHub API returns a SAML error, the system will automatically
fall back to gathering metrics from public web sources.
"""

    try:
        with spinner("Researching your query"):
            result = get_agent().invoke(
                {"messages": [{"role": "user", "content": enhanced_query}]}
            )

        response = result["messages"][-1].content

        print(response)

        # Generate a report identifier from the query
        clean_query = re.sub(r"[^\w\s-]", "", query)[:50].strip().replace(" ", "_")
        report_path = save_report_to_file(response, "query", clean_query)
        print(f"\n📄 Report saved: {report_path}")

        # Export if requested
        if args.output:
            export_result(response, args.output, args.format)

        return 0

    except Exception as e:
        logger.error(f"Query failed: {e}")
        print(f"\nError: {e}", file=sys.stderr)
        return 1


def evaluate_command(args):
    """Evaluate a single repository."""
    repo = args.repo
    query = f"Evaluate {repo}"

    if args.use_case:
        query += f" for {args.use_case}"

    logger.info(f"CLI: Evaluating {repo}")
    print(f"\n{'='*80}")
    print(f"Evaluating: {repo}")
    if args.use_case:
        print(f"Use Case: {args.use_case}")
    print(f"{'='*80}\n")

    try:
        with spinner(f"Researching {repo}"):
            result = get_agent().invoke(
                {"messages": [{"role": "user", "content": query}]}
            )

        response = result["messages"][-1].content

        print(response)

        # Save report to file
        report_path = save_report_to_file(response, "evaluation", repo)
        print(f"\n📄 Report saved: {report_path}")

        # Export if requested (additional format)
        if args.output:
            export_result(response, args.output, args.format)

        return 0

    except Exception as e:
        logger.error(f"Evaluation failed: {e}")
        print(f"\nError: {e}", file=sys.stderr)
        return 1


def compare_command(args):
    """Compare multiple repositories."""
    repos = args.repos
    query = f"Compare {' vs '.join(repos)}"

    if args.use_case:
        query += f" for {args.use_case}"

    logger.info(f"CLI: Comparing {len(repos)} repositories")
    print(f"\n{'='*80}")
    print(f"Comparing: {', '.join(repos)}")
    if args.use_case:
        print(f"Use Case: {args.use_case}")
    print(f"{'='*80}\n")

    try:
        with spinner(f"Comparing {len(repos)} repositories"):
            result = get_agent().invoke(
                {"messages": [{"role": "user", "content": query}]}
            )

        response = result["messages"][-1].content

        print(response)

        # Save report to file
        comparison_id = "_vs_".join(r.replace("/", "_") for r in repos)
        report_path = save_report_to_file(response, "comparison", comparison_id)
        print(f"\n📄 Report saved: {report_path}")

        # Export if requested (additional format)
        if args.output:
            export_result(response, args.output, args.format)

        return 0

    except Exception as e:
        logger.error(f"Comparison failed: {e}")
        print(f"\nError: {e}", file=sys.stderr)
        return 1


def search_command(args):
    """Search for technologies by tags or description."""
    query = f"Find technologies matching: {args.query}"

    if args.tags:
        query += f" with tags: {', '.join(args.tags)}"

    if args.min_viability:
        query += f" with minimum viability score of {args.min_viability}"

    logger.info(f"CLI: Searching for technologies")
    print(f"\n{'='*80}")
    print(f"Searching: {args.query}")
    if args.tags:
        print(f"Tags: {', '.join(args.tags)}")
    if args.min_viability:
        print(f"Min Viability: {args.min_viability}")
    print(f"{'='*80}\n")

    try:
        with spinner("Searching technologies"):
            result = get_agent().invoke(
                {"messages": [{"role": "user", "content": query}]}
            )

        response = result["messages"][-1].content

        print(response)

        # Export if requested
        if args.output:
            export_result(response, args.output, args.format)

        return 0

    except Exception as e:
        logger.error(f"Search failed: {e}")
        print(f"\nError: {e}", file=sys.stderr)
        return 1


def discover_command(args):
    """Discover new technologies matching a use case description."""
    description = args.description

    query = f"""Discover new technologies for: {description}

Your task is to find GitHub repositories and open source projects that match this use case.

## Instructions:
1. Use the web-research-agent to search for technologies matching this description
2. Search for terms like:
   - "{description} open source"
   - "{description} GitHub"
   - "{description} framework library"
   - "best {description} tools 2024 2025"
3. For each technology found, provide:
   - Name of the project
   - GitHub repository URL (REQUIRED)
   - Brief description of what it does
   - Why it's relevant to the use case
   - Star count if mentioned in search results

## Output Format:
Return a structured list of discovered technologies:

# Technology Discovery: {description}

## Found [N] Candidate Technologies

### 1. [Technology Name]
- **GitHub**: [URL]
- **Website**: [URL if available]
- **Description**: [What it does]
- **Relevance**: [Why it matches the use case]
- **Popularity**: [Stars/adoption indicators if known]

### 2. [Technology Name]
...

## Recommendations
- **Most Promising**: [Which one to evaluate first and why]
- **Worth Watching**: [Others that show potential]

## Suggested Next Steps
To evaluate any of these, run:
```
python cli.py evaluate [owner/repo]
```

DO NOT evaluate the technologies yet - just discover and list them with links.
"""

    logger.info(f"CLI: Discovering technologies for: {description}")
    print(f"\n{'='*80}")
    print(f"Discovering: {description}")
    if args.limit:
        print(f"Limit: {args.limit} technologies")
    print(f"{'='*80}\n")

    try:
        with spinner(f"Discovering technologies"):
            result = get_agent().invoke(
                {"messages": [{"role": "user", "content": query}]}
            )

        response = result["messages"][-1].content

        print(response)

        # Save discovery report
        report_path = save_report_to_file(response, "discovery", description[:50])
        print(f"\n📄 Report saved: {report_path}")

        # Parse and store discoveries in Elasticsearch
        try:
            parsed = parse_discoveries(response)
            if parsed["technologies"]:
                doc_id = store_discovery(
                    use_case=description,
                    technologies=parsed["technologies"],
                    most_promising=parsed["most_promising"],
                    full_report=response,
                )
                tech_count = len(parsed["technologies"])
                print(
                    f"💾 Stored {tech_count} technologies in knowledge base (doc: {doc_id[:8]}...)"
                )
                logger.info(
                    f"Stored discovery with {tech_count} technologies, doc_id={doc_id}"
                )
            else:
                logger.warning("No technologies parsed from discovery response")
        except Exception as store_err:
            logger.warning(f"Failed to store discovery in Elasticsearch: {store_err}")
            # Don't fail the command if storage fails

        # Export if requested
        if args.output:
            export_result(response, args.output, args.format)

        return 0

    except Exception as e:
        logger.error(f"Discovery failed: {e}")
        print(f"\nError: {e}", file=sys.stderr)
        return 1


def batch_command(args):
    """Batch evaluate multiple repositories (stub)."""
    logger.info("CLI: Batch evaluation requested")
    print("\n" + "=" * 80)
    print("BATCH EVALUATION MODE")
    print("=" * 80)
    print("\n⚠️  Batch mode is not yet implemented.")
    print("This feature will allow evaluating multiple repositories from a file.")
    print("\nPlanned usage:")
    print("  cli.py batch repos.txt --output results/")
    print("\nStay tuned for future updates!")
    print("=" * 80 + "\n")
    return 1


def export_result(content: str, output_path: str, format_type: str):
    """
    Export result to file.

    Args:
        content: Content to export
        output_path: Path to output file
        format_type: Export format (json, csv, markdown)
    """
    logger.info(f"Exporting result to {output_path} as {format_type}")

    try:
        if format_type == "markdown":
            with open(output_path, "w") as f:
                f.write(content)
            print(f"\n✓ Exported to {output_path} (Markdown)")

        elif format_type == "json":
            # Wrap content in JSON structure
            data = {
                "timestamp": datetime.utcnow().isoformat(),
                "content": content,
            }
            with open(output_path, "w") as f:
                json.dump(data, f, indent=2)
            print(f"\n✓ Exported to {output_path} (JSON)")

        elif format_type == "csv":
            print(f"\n⚠️  CSV export not yet fully implemented for this report type")
            print(f"Content saved as text to {output_path}")
            with open(output_path, "w") as f:
                f.write(content)

    except Exception as e:
        logger.error(f"Export failed: {e}")
        print(f"\n⚠️  Export failed: {e}", file=sys.stderr)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="DevRel Research Agent - Technology vetting and research",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Ask a natural language question (LLM finds repos)
  %(prog)s ask "What are the best Python web frameworks and how do they compare?"
  %(prog)s ask "Evaluate the top 3 LLM orchestration libraries"
  %(prog)s ask "Compare MongoDB vs PostgreSQL for a real-time analytics use case"

  # Evaluate a single repository
  %(prog)s evaluate langchain-ai/deepagents

  # Evaluate with specific use case
  %(prog)s evaluate langchain-ai/deepagents --use-case "building research agents"

  # Compare multiple repositories
  %(prog)s compare crewAIInc/crewAI microsoft/autogen --use-case "multi-agent orchestration"

  # Discover new technologies for a use case
  %(prog)s discover "UI frameworks for multi-modal AI chat interactions"

  # Search previously researched technologies
  %(prog)s search "AI agent frameworks" --tags ai-agents python

  # Export results
  %(prog)s evaluate langchain-ai/deepagents --output report.md --format markdown
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Ask command (natural language - LLM finds repos)
    ask_parser = subparsers.add_parser(
        "ask", help="Ask a natural language question - LLM finds and analyzes repos"
    )
    ask_parser.add_argument(
        "query",
        help="Natural language query (e.g., 'Compare the top Python web frameworks')",
    )
    ask_parser.add_argument("--output", "-o", help="Output file path")
    ask_parser.add_argument(
        "--format",
        "-f",
        choices=["json", "csv", "markdown"],
        default="markdown",
        help="Export format",
    )
    ask_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed agent activity in real-time",
    )

    # Evaluate command
    evaluate_parser = subparsers.add_parser(
        "evaluate", help="Evaluate a single repository"
    )
    evaluate_parser.add_argument("repo", help="Repository to evaluate (owner/repo)")
    evaluate_parser.add_argument(
        "--use-case", "-u", help="Specific use case to evaluate for"
    )
    evaluate_parser.add_argument("--output", "-o", help="Output file path")
    evaluate_parser.add_argument(
        "--format",
        "-f",
        choices=["json", "csv", "markdown"],
        default="markdown",
        help="Export format",
    )
    evaluate_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed agent activity in real-time",
    )

    # Compare command
    compare_parser = subparsers.add_parser(
        "compare", help="Compare multiple repositories"
    )
    compare_parser.add_argument(
        "repos", nargs="+", help="Repositories to compare (owner/repo)"
    )
    compare_parser.add_argument(
        "--use-case", "-u", help="Specific use case to compare for"
    )
    compare_parser.add_argument("--output", "-o", help="Output file path")
    compare_parser.add_argument(
        "--format",
        "-f",
        choices=["json", "csv", "markdown"],
        default="markdown",
        help="Export format",
    )
    compare_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed agent activity in real-time",
    )

    # Discover command
    discover_parser = subparsers.add_parser(
        "discover", help="Discover new technologies for a use case"
    )
    discover_parser.add_argument(
        "description", help="Description of what you're looking for"
    )
    discover_parser.add_argument(
        "--limit",
        "-l",
        type=int,
        default=10,
        help="Maximum technologies to find (default: 10)",
    )
    discover_parser.add_argument("--output", "-o", help="Output file path")
    discover_parser.add_argument(
        "--format",
        "-f",
        choices=["json", "csv", "markdown"],
        default="markdown",
        help="Export format",
    )
    discover_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed agent activity in real-time",
    )

    # Search command (searches existing research in Elasticsearch)
    search_parser = subparsers.add_parser(
        "search", help="Search previously researched technologies"
    )
    search_parser.add_argument("query", help="Search query or description")
    search_parser.add_argument("--tags", "-t", nargs="+", help="Filter by tags")
    search_parser.add_argument(
        "--min-viability", "-m", type=float, help="Minimum viability score (0-100)"
    )
    search_parser.add_argument("--output", "-o", help="Output file path")
    search_parser.add_argument(
        "--format",
        "-f",
        choices=["json", "csv", "markdown"],
        default="markdown",
        help="Export format",
    )
    search_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed agent activity in real-time",
    )

    # Batch command (stub)
    batch_parser = subparsers.add_parser(
        "batch", help="Batch evaluate repositories from file"
    )
    batch_parser.add_argument("input_file", help="File containing list of repositories")
    batch_parser.add_argument("--output", "-o", help="Output directory")
    batch_parser.add_argument(
        "--format",
        "-f",
        choices=["json", "csv", "markdown"],
        default="markdown",
        help="Export format",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Set verbose mode if specified
    if hasattr(args, "verbose") and args.verbose:
        set_verbose_mode(True)
        print("🔍 Verbose mode enabled - showing detailed agent activity\n")

    # Route to appropriate command
    if args.command == "ask":
        return ask_command(args)
    elif args.command == "evaluate":
        return evaluate_command(args)
    elif args.command == "compare":
        return compare_command(args)
    elif args.command == "discover":
        return discover_command(args)
    elif args.command == "search":
        return search_command(args)
    elif args.command == "batch":
        return batch_command(args)
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
