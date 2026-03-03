"""
Web search tools using Tavily API with caching and retry logic.

Extracted here (instead of subagents/web_agent.py) to break the circular
dependency: github_tools.py needs tavily_search for SAML fallback, but
github_tools is itself part of the tools package.
"""

from tavily import TavilyClient
from langchain_core.tools import tool

from config import config
from exceptions import SearchError
from utils.logging_utils import get_logger
from utils.retry_utils import with_retry
from tools.elasticsearch_tools import (
    get_cached_search,
    store_search_cache,
    store_adoption_signal,
)

logger = get_logger(__name__)

# Initialize Tavily client at module load (key must be present)
_tavily_client = None
if config.TAVILY_API_KEY:
    _tavily_client = TavilyClient(api_key=config.TAVILY_API_KEY)


@with_retry(max_attempts=3, exceptions=(SearchError,))
def _call_tavily(query: str, max_results: int) -> dict:
    """Make the raw Tavily API call. Retried up to 3x on SearchError."""
    if not _tavily_client:
        raise SearchError("Tavily API key not configured")
    try:
        return _tavily_client.search(
            query=query,
            max_results=max_results,
            search_depth="advanced",
            include_answer=True,
        )
    except Exception as e:
        raise SearchError(f"Tavily search failed: {e}") from e


@tool
def tavily_search(query: str, max_results: int = 10, cache_days: int = 7) -> dict:
    """
    Search the web for information using Tavily API.
    Optimized for finding technical content about frameworks and libraries.
    Results are cached to reduce API costs. Retries up to 3x on failure.

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
        cached["cached"] = True
        return cached

    logger.info(f"Searching Tavily for: {query}")
    results = _call_tavily(query, max_results)
    logger.info(f"Found {len(results.get('results', []))} results for query: {query}")

    # Cache the results
    store_search_cache(query, results, search_type="tavily")
    results["cached"] = False
    return results


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
