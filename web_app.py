"""
Web UI for the DevRel Research Agent.

FastAPI server with WebSocket for real-time agent activity monitoring.
Run with: uvicorn web_app:app --reload --port 8000
"""

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import markdown
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader

from agent import get_agent, MODELS, DEFAULT_MODEL
from config import config
from cli import save_report_to_file
from utils.logging_utils import setup_logging, get_logger

# Setup logging
setup_logging()
logger = get_logger(__name__)

# Paths
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
REPORTS_DIR = BASE_DIR / "research_reports"

# Ensure directories exist
STATIC_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

# Jinja2 setup
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

# FastAPI app
app = FastAPI(title="DevRel Research Agent", version="1.0.0")

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# =============================================================================
# Elastic tool names for special handling
# =============================================================================

ELASTIC_TOOL_NAMES = {
    "semantic_search_technologies",
    "search_technologies_by_tags",
    "get_repository_trends",
    "get_repository_timeseries",
    "get_repository_stats",
    "get_latest_snapshot",
    "get_adoption_signals",
    "get_adoption_signals_by_type",
    "count_adoption_signals",
    "get_latest_research_report",
    "get_cached_research_report",
    "check_search_cache",
    "check_github_metrics_cache",
    "get_past_discoveries",
    "search_discoveries_by_use_case",
    "get_all_discovered_repositories",
}

# Mapping from LangChain tool name to Elastic Agent Builder tool ID
ELASTIC_TOOL_ID_MAP = {
    "semantic_search_technologies": "find-similar-technologies",
    "search_technologies_by_tags": "search-by-tags",
    "get_repository_trends": "get-trend-data",
    "get_repository_timeseries": "get-repo-timeseries",
    "get_repository_stats": "get-repo-timeseries-stats",
    "get_latest_snapshot": "get-latest-snapshot",
    "get_adoption_signals": "get-adoption-signals",
    "get_adoption_signals_by_type": "get-adoption-signals-by-type",
    "count_adoption_signals": "count-adoption-signals",
    "get_latest_research_report": "get-latest-report",
    "get_cached_research_report": "get-cached-report",
    "check_search_cache": "get-cached-search",
    "check_github_metrics_cache": "get-cached-github-metrics",
    "get_past_discoveries": "get-past-discoveries",
    "search_discoveries_by_use_case": "search-discoveries-by-use-case",
    "get_all_discovered_repositories": "get-all-discovered-repos",
}

# All orchestrator-level tool names
ORCHESTRATOR_TOOL_NAMES = {
    "find_similar_technologies",
    "compare_technologies",
    "get_trend_data",
    "search_by_tags",
    "calculate_viability_score",
    "store_research_report",
}

# Subagent tool mapping
SUBAGENT_TOOL_MAP = {
    # metrics-agent tools
    "fetch_repo_metrics": "metrics-agent",
    # sentiment-agent tools
    "fetch_recent_issues": "sentiment-agent",
    "fetch_repo_discussions": "sentiment-agent",
    # web-research-agent tools
    "tavily_search": "web-research-agent",
    "record_adoption_signal": "web-research-agent",
    # store_research_snapshot is used by BOTH metrics and sentiment agents;
    # identify by the tags from the surrounding chain instead (handled via on_chain_start)
}

# Phase detection based on tool names
def detect_phase(tool_name: str, agent_name: str) -> str:
    """Detect the current research phase based on the tool being called."""
    if tool_name in ELASTIC_TOOL_NAMES:
        if "cache" in tool_name.lower() or "cached" in tool_name.lower():
            return "checking_cache"
        if "snapshot" in tool_name.lower() or "report" in tool_name.lower():
            return "checking_cache"
        return "data_retrieval"
    if tool_name in ("fetch_repo_metrics", "store_research_snapshot"):
        return "fetching_metrics"
    if tool_name in ("fetch_recent_issues", "fetch_repo_discussions"):
        return "analyzing_sentiment"
    if tool_name in ("tavily_search", "record_adoption_signal"):
        return "web_research"
    if tool_name == "calculate_viability_score":
        return "scoring"
    if tool_name == "store_research_report":
        return "storing_report"
    if tool_name in ("find_similar_technologies", "compare_technologies",
                      "get_trend_data", "search_by_tags"):
        return "data_retrieval"
    return "processing"


def identify_agent(event: dict) -> str:
    """Identify which agent an event belongs to based on event metadata."""
    tags = event.get("tags", [])
    name = event.get("name", "")

    # Check tags for subagent names
    for tag in tags:
        if "metrics" in tag.lower():
            return "metrics-agent"
        if "sentiment" in tag.lower():
            return "sentiment-agent"
        if "web" in tag.lower():
            return "web-research-agent"
        if "elastic" in tag.lower():
            return "elastic-agent"

    # Check tool name mapping
    if name in SUBAGENT_TOOL_MAP:
        return SUBAGENT_TOOL_MAP[name]
    if name in ELASTIC_TOOL_NAMES:
        return "elastic-agent"
    if name in ORCHESTRATOR_TOOL_NAMES:
        return "orchestrator"

    return "orchestrator"


def make_serializable(obj):
    """Make an object JSON-serializable by converting non-standard types."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [make_serializable(item) for item in obj]
    # Pydantic v2 models (e.g. deepagents' Todo objects)
    if hasattr(obj, "model_dump"):
        return make_serializable(obj.model_dump())
    # Pydantic v1 models
    if hasattr(obj, "dict") and callable(obj.dict):
        return make_serializable(obj.dict())
    # Fallback: convert to string, but truncate very long values
    s = str(obj)
    if len(s) > 500:
        return s[:500] + "..."
    return s


# =============================================================================
# Routes
# =============================================================================

@app.get("/")
async def root():
    """Serve the main dashboard page."""
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/reports/{report_id}")
async def get_report(report_id: str):
    """Serve a rendered HTML version of a markdown report."""
    # Find the report file
    report_path = REPORTS_DIR / f"{report_id}.md"
    if not report_path.exists():
        # Try to find by partial match
        matches = list(REPORTS_DIR.glob(f"*{report_id}*"))
        if matches:
            report_path = matches[0]
        else:
            return HTMLResponse("<h1>Report not found</h1>", status_code=404)

    # Read the markdown
    md_content = report_path.read_text()

    # Strip YAML frontmatter if present
    if md_content.startswith("---"):
        end = md_content.find("---", 3)
        if end != -1:
            md_content = md_content[end + 3:].strip()

    # Convert to HTML
    md_extensions = [
        "tables",
        "fenced_code",
        "toc",
        "sane_lists",
    ]
    html_content = markdown.markdown(md_content, extensions=md_extensions)

    # Render with template
    template = jinja_env.get_template("report.html")
    rendered = template.render(
        title=report_path.stem.replace("_", " ").title(),
        content=html_content,
        generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
        filename=report_path.name,
    )
    return HTMLResponse(rendered)


@app.get("/api/models")
async def list_models():
    """Return available models."""
    return {"models": list(MODELS.keys()), "default": DEFAULT_MODEL}


# =============================================================================
# WebSocket endpoint for real-time research streaming
# =============================================================================

@app.websocket("/ws/research")
async def websocket_research(websocket: WebSocket):
    """
    WebSocket endpoint that accepts a research query,
    runs the agent with astream_events, and streams all
    activity back to the client in real-time.
    """
    await websocket.accept()
    logger.info("WebSocket connection accepted")

    try:
        # Receive the research request
        data = await websocket.receive_json()
        query = data.get("query", "")
        model = data.get("model", DEFAULT_MODEL)

        if not query:
            await websocket.send_json({"type": "error", "message": "No query provided"})
            await websocket.close()
            return

        logger.info(f"WebSocket research request: query='{query[:80]}...', model={model}")

        # Send acknowledgement
        await websocket.send_json({
            "type": "status",
            "message": "Initializing agent...",
            "phase": "initializing",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # Get the agent
        try:
            agent = get_agent(model=model)
        except Exception as e:
            await websocket.send_json({
                "type": "error",
                "message": f"Failed to initialize agent: {str(e)}",
            })
            await websocket.close()
            return

        await websocket.send_json({
            "type": "status",
            "message": "Agent ready. Starting research...",
            "phase": "starting",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # Stream events from the agent
        final_response = ""
        event_count = 0

        try:
            async for event in agent.astream_events(
                {"messages": [{"role": "user", "content": query}]},
                config={"recursion_limit": config.RECURSION_LIMIT},
                version="v2",
            ):
                event_kind = event.get("event", "")
                event_name = event.get("name", "")
                event_data = event.get("data", {})
                event_tags = event.get("tags", [])
                event_count += 1

                msg = None

                # --- Tool Start ---
                if event_kind == "on_tool_start":
                    tool_input = event_data.get("input", {})
                    agent_name = identify_agent(event)
                    phase = detect_phase(event_name, agent_name)
                    is_elastic = event_name in ELASTIC_TOOL_NAMES

                    # write_todos: emit a plan update instead of a generic tool event
                    if event_name == "write_todos":
                        todos = tool_input.get("todos", [])
                        msg = {
                            "type": "todos_update",
                            "agent": agent_name,
                            "todos": make_serializable(todos),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    else:
                        msg = {
                            "type": "tool_start",
                            "agent": agent_name,
                            "tool": event_name,
                            "params": make_serializable(tool_input),
                            "phase": phase,
                            "is_elastic_tool": is_elastic,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }

                        # Add Elastic-specific metadata
                        if is_elastic:
                            msg["elastic_tool_id"] = ELASTIC_TOOL_ID_MAP.get(
                                event_name, event_name
                            )

                # --- Tool End ---
                elif event_kind == "on_tool_end":
                    # Skip write_todos — the plan card already visualizes it
                    if event_name == "write_todos":
                        pass
                    else:
                        agent_name = identify_agent(event)
                        output = event_data.get("output", "")

                        # Summarize the output
                        output_summary = ""
                        if isinstance(output, dict):
                            if "error" in output:
                                output_summary = f"Error: {output['error']}"
                            elif "results" in output:
                                count = len(output["results"]) if isinstance(output["results"], list) else 0
                                output_summary = f"{count} results returned"
                            else:
                                output_summary = f"Response with {len(output)} fields"
                        elif isinstance(output, str):
                            output_summary = output[:200] + ("..." if len(output) > 200 else "")
                        elif hasattr(output, "__class__") and "Command" in type(output).__name__:
                            # LangGraph Command objects from subagent task() calls — show clean summary
                            output_summary = "Subagent task completed"
                        else:
                            output_summary = str(output)[:200]

                        msg = {
                            "type": "tool_end",
                            "agent": agent_name,
                            "tool": event_name,
                            "output_summary": output_summary,
                            "is_elastic_tool": event_name in ELASTIC_TOOL_NAMES,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }

                # --- Chain Start (agent/subagent activation) ---
                elif event_kind == "on_chain_start":
                    # Detect subagent delegation via task() calls or named subagent chains
                    # deepagents may use the subagent name directly as the chain name
                    known_subagents = {
                        "metrics-agent", "metrics_agent",
                        "sentiment-agent", "sentiment_agent",
                        "web-research-agent", "web_research_agent",
                        "elastic-agent", "elastic_agent",
                    }
                    subagent_name_map = {
                        "metrics-agent": "metrics-agent",
                        "metrics_agent": "metrics-agent",
                        "sentiment-agent": "sentiment-agent",
                        "sentiment_agent": "sentiment-agent",
                        "web-research-agent": "web-research-agent",
                        "web_research_agent": "web-research-agent",
                        "elastic-agent": "elastic-agent",
                        "elastic_agent": "elastic-agent",
                    }

                    is_task_delegation = event_name == "task" or "subagent" in event_name.lower()
                    is_named_subagent = event_name in known_subagents

                    if is_task_delegation or is_named_subagent:
                        task_input = event_data.get("input", {})
                        description = ""
                        target_agent = None

                        if is_named_subagent:
                            # Chain is named after the subagent directly
                            target_agent = subagent_name_map.get(event_name)
                        elif isinstance(task_input, dict):
                            description = str(task_input.get("description", ""))[:200]
                            # Try to extract which subagent is being called
                            subagent_field = str(task_input.get("subagent", task_input.get("agent", ""))).lower()
                            target_agent = subagent_name_map.get(subagent_field)

                        agent_name = target_agent or "orchestrator"
                        msg = {
                            "type": "agent_start",
                            "agent": agent_name,
                            "detail": f"Delegating task: {description}" if description else f"Starting {agent_name}",
                            "phase": "delegating",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }

                # --- Chain End ---
                elif event_kind == "on_chain_end":
                    pass  # We handle completion via tool_end and the final message

                # --- Chat Model Stream (LLM tokens) ---
                elif event_kind == "on_chat_model_stream":
                    chunk = event_data.get("chunk", None)
                    if chunk:
                        content = ""
                        if hasattr(chunk, "content"):
                            content = chunk.content
                        elif isinstance(chunk, dict):
                            content = chunk.get("content", "")

                        if content:
                            # Only send periodic LLM updates, not every token
                            if event_count % 5 == 0:
                                msg = {
                                    "type": "llm_token",
                                    "agent": identify_agent(event),
                                    "content": content,
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                }

                # --- Chat Model End (full response) ---
                elif event_kind == "on_chat_model_end":
                    output = event_data.get("output", None)
                    if output:
                        raw_content = ""
                        if hasattr(output, "content"):
                            raw_content = output.content
                        elif isinstance(output, dict):
                            raw_content = output.get("content", "")

                        # Anthropic returns content as a list of blocks:
                        # [{"type": "text", "text": "..."}, ...]
                        # OpenAI/others return a plain string.
                        content = ""
                        if isinstance(raw_content, str):
                            content = raw_content
                        elif isinstance(raw_content, list):
                            content = "\n".join(
                                block.get("text", "")
                                for block in raw_content
                                if isinstance(block, dict) and block.get("type") == "text"
                            ).strip()

                        if content and len(content) > 100:
                            # This might be the final report
                            final_response = content

                # Send the message if we have one
                if msg:
                    try:
                        await websocket.send_json(msg)
                    except Exception as send_err:
                        logger.warning(
                            f"Failed to send WebSocket message: {str(send_err) or repr(send_err)}",
                            exc_info=True,
                        )
                        break

        except Exception as stream_err:
            error_detail = str(stream_err) or repr(stream_err)
            logger.error(f"Streaming error: {error_detail}", exc_info=True)
            await websocket.send_json({
                "type": "error",
                "message": f"Agent error: {error_detail}",
            })

        # --- Completion: save report and send link ---
        if final_response:
            # Save the report
            clean_query = re.sub(r"[^\w\s-]", "", query)[:50].strip().replace(" ", "_")
            report_path = save_report_to_file(final_response, "query", clean_query)
            report_id = report_path.stem  # filename without extension

            await websocket.send_json({
                "type": "complete",
                "message": "Research complete!",
                "report_url": f"/reports/{report_id}",
                "report_filename": report_path.name,
                "word_count": len(final_response.split()),
                "event_count": event_count,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        else:
            await websocket.send_json({
                "type": "complete",
                "message": "Research complete, but no report was generated.",
                "event_count": event_count,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        error_detail = str(e) or repr(e)
        logger.error(f"WebSocket error: {error_detail}", exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"Server error: {error_detail}",
            })
        except Exception:
            pass


# =============================================================================
# Entry point
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    print("\n" + "=" * 60)
    print("  DevRel Research Agent - Web UI")
    print("  Open http://localhost:8000 in your browser")
    print("=" * 60 + "\n")

    uvicorn.run(
        "web_app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
