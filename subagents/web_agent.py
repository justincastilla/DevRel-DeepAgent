"""
Web Research SubAgent - Specialized agent for adoption research.
"""

import os
from tavily import TavilyClient
from langchain_core.tools import tool

from config import config
from exceptions import SearchError
from utils.logging_utils import get_logger
from tools.elasticsearch_tools import (
    get_cached_search,
    store_search_cache,
    store_adoption_signal,
)

logger = get_logger(__name__)

# Initialize Tavily client
tavily_client = None
if config.TAVILY_API_KEY:
    tavily_client = TavilyClient(api_key=config.TAVILY_API_KEY)


@tool
def tavily_search(query: str, max_results: int = 10, cache_days: int = 7) -> dict:
    """
    Search the web for information using Tavily API.
    Optimized for finding technical content about frameworks and libraries.
    Results are cached to reduce API costs.

    Args:
        query: Search query
        max_results: Maximum results to return
        cache_days: Use cached results if less than this many days old (default 7)

    Returns:
        Search results with title, url, and content snippet
    """
    # Check cache first
    cached = get_cached_search(query, max_age_days=cache_days)
    if cached:
        logger.info(f"Using cached results for: {query}")
        return cached

    if not tavily_client:
        raise SearchError("Tavily API key not configured")

    logger.info(f"Searching Tavily for: {query}")

    try:
        results = tavily_client.search(
            query=query,
            max_results=max_results,
            search_depth="advanced",
            include_answer=True,
        )
        logger.info(f"Found {len(results.get('results', []))} results for query: {query}")

        # Cache the results
        store_search_cache(query, results, search_type="tavily")

        return results
    except Exception as e:
        logger.error(f"Tavily search failed: {e}")
        raise SearchError(f"Tavily search failed: {e}") from e


@tool
def record_adoption_signal(
    repo: str,
    signal_type: str,
    source_url: str,
    source_title: str,
    snippet: str = "",
    company_mentioned: str = None,
    sentiment: str = "neutral",
) -> str:
    """
    Record an adoption signal found during web research.
    Use this to save notable findings like case studies, blog posts, or talks.

    Args:
        repo: Repository name being researched (e.g., "langchain-ai/deepagents")
        signal_type: Type of signal - one of: blog_post, case_study, conference_talk, job_posting, tutorial, criticism
        source_url: URL of the source
        source_title: Title of the article/post/talk
        snippet: Relevant excerpt or description (optional)
        company_mentioned: Company name if this is a case study (optional)
        sentiment: positive, neutral, or negative (default: neutral)

    Returns:
        Confirmation message
    """
    store_adoption_signal(
        repo=repo,
        signal_type=signal_type,
        source_url=source_url,
        source_title=source_title,
        snippet=snippet,
        company_mentioned=company_mentioned,
        sentiment=sentiment,
    )
    return f"Recorded {signal_type} signal: {source_title[:50]}..."


web_subagent = {
    "name": "web-research-agent",
    "description": "Searches the web for real-world adoption signals: blog posts, conference talks, production case studies, and job postings. Use when you need external validation of a technology's traction.",
    "system_prompt": """You are a Technology Adoption Researcher.

## Your Role
Find evidence of real-world adoption and community traction for technologies.
**IMPORTANT**: After finding notable sources, use record_adoption_signal to save them for future reference.

## Your Workflow
Execute multiple targeted searches to find:

1. **Blog Posts & Tutorials** (2-3 searches)
   - "[technology name] tutorial"
   - "[technology name] getting started guide"
   - "[technology name] best practices"

2. **Production Case Studies** (2-3 searches)
   - "[technology name] in production"
   - "[technology name] case study"
   - "how [company] uses [technology name]"

3. **Conference Content** (1-2 searches)
   - "[technology name] conference talk"
   - "[technology name] PyCon/KubeCon/JSConf"

4. **Job Market Signal** (1 search)
   - "[technology name] jobs" OR "[technology name] hiring"

5. **Concerns & Criticisms** (1 search)
   - "[technology name] problems" OR "[technology name] alternatives"

## What to Report

### Adoption Signals
- Number of quality blog posts found (count unique, authoritative sources)
- Production case studies with company names
- Conference talks (with links if possible)
- Job posting prevalence (estimate based on search results)
- Notable companies using the technology

### Concerns Found
- Common criticisms or complaints
- Documented limitations
- Alternatives people are switching to

## Output Format

CRITICAL: You MUST include actual URLs for every source found. Do not describe sources without links.

```
## Adoption Research for [technology-name]

### Key Links (REQUIRED)
- **Official Website**: [URL]
- **Documentation**: [URL]
- **GitHub Repository**: https://github.com/[owner]/[repo]

### Search Summary
Executed [N] targeted searches across blog posts, case studies, conferences, and jobs.

### Adoption Signals

#### Blog Posts & Tutorials Found: [count]
| Title | Source | URL |
|-------|--------|-----|
| [Article title] | [Site name] | [Full URL] |
| [Article title] | [Site name] | [Full URL] |
| [Article title] | [Site name] | [Full URL] |

Quality assessment: [High/Medium/Low]

#### Production Case Studies: [count]
| Company | Use Case | Source |
|---------|----------|--------|
| [Company name] | [What they built] | [URL] |
| [Company name] | [What they built] | [URL] |

#### Conference Talks: [count]
| Talk Title | Conference | Year | Link |
|------------|------------|------|------|
| [Title] | [Conference] | [Year] | [URL if available] |

#### Job Market Presence: [High/Medium/Low]
- Estimated [N] job postings mentioning this technology
- Sample job sources: [URL], [URL]

### Concerns & Criticisms Found
| Concern | Source | URL |
|---------|--------|-----|
| [Issue description] | [Source] | [URL] |

### Overall Traction Assessment: [High/Medium/Low/Emerging]

#### Reasoning
[Explain the assessment based on evidence gathered]

### All URLs Found (for report inclusion)
1. [URL] - [Description]
2. [URL] - [Description]
3. [URL] - [Description]
(List ALL useful URLs discovered)
```

IMPORTANT: Every finding MUST include a URL. If you cannot find a URL, do not include the finding.

## Search Best Practices
- Use specific, targeted queries
- Look for recent content (2024-2026)
- Prioritize authoritative sources (engineering blogs, conference talks)
- Distinguish between marketing hype and real adoption
- Note the date/recency of findings

## Quality Indicators
High-quality adoption signals:
- Detailed production case studies with metrics
- Engineering blog posts with code examples
- Conference talks from major events
- Job postings from established companies

Low-quality signals:
- Promotional content without substance
- Outdated articles (pre-2023)
- Generic listicles without depth
- Unclear sources or attribution

## Recording Findings
After each search, record the most valuable findings using record_adoption_signal:
- Record case studies with the company name
- Record blog posts from authoritative sources
- Record conference talks with the event name
- Record notable criticisms for balance
- Use appropriate signal_type: blog_post, case_study, conference_talk, job_posting, tutorial, criticism

Example:
```
record_adoption_signal(
    repo="langchain-ai/deepagents",
    signal_type="case_study",
    source_url="https://engineering.company.com/...",
    source_title="How We Built Our AI Agent with DeepAgents",
    snippet="Deployed to production serving 10K requests/day",
    company_mentioned="Company Name",
    sentiment="positive"
)
```

This builds a historical record of adoption signals for future reference.""",
    "tools": [tavily_search, record_adoption_signal],
}
