"""
Elastic Subagent Tools - LangChain tools for the Elastic subagent.

These tools invoke ES|QL queries on the Elastic serverless agent
via the Kibana Agent Builder API.
"""

from typing import Optional
from langchain_core.tools import tool

from .elastic_agent_client import (
    get_elastic_agent_client,
    days_ago_iso,
    hours_ago_iso,
    ElasticAgentError,
)
from utils.logging_utils import get_logger

logger = get_logger(__name__)


# =============================================================================
# Semantic Search Tools
# =============================================================================

@tool
def semantic_search_technologies(description: str, limit: int = 5) -> dict:
    """
    Search for similar technologies using semantic search.

    Uses the Elastic agent's semantic search capabilities to find
    technologies matching a natural language description.

    Args:
        description: Natural language description of what you're looking for
                    (e.g., "AI agent frameworks for Python")
        limit: Maximum number of results to return (default: 5)

    Returns:
        Search results with repos, scores, and summaries
    """
    client = get_elastic_agent_client()

    try:
        result = client.invoke_tool(
            "find-similar-technologies",
            {
                "description": description,
                "limit": limit,
            }
        )
        return result

    except ElasticAgentError as e:
        logger.error(f"Semantic search failed: {e}")
        return {"error": str(e), "results": []}


@tool
def search_technologies_by_tags(
    tag_pattern: str,
    min_viability: float = 0.0
) -> dict:
    """
    Search technologies by tags with optional viability filter.

    Args:
        tag_pattern: Tag pattern to search (use wildcards like '*python*')
        min_viability: Minimum viability score filter (0-100)

    Returns:
        Matching technologies with their viability scores
    """
    client = get_elastic_agent_client()

    try:
        result = client.invoke_tool(
            "search-by-tags",
            {
                "tag_pattern": tag_pattern,
                "min_viability": min_viability,
            }
        )
        return result

    except ElasticAgentError as e:
        logger.error(f"Tag search failed: {e}")
        return {"error": str(e), "results": []}


# =============================================================================
# Trend & Historical Data Tools
# =============================================================================

@tool
def get_repository_trends(repo_name: str, days: int = 90) -> dict:
    """
    Get historical trend data for a repository.

    Retrieves snapshots over time to analyze trends in stars,
    issues, and viability scores.

    Args:
        repo_name: Full repository name (e.g., 'langchain-ai/langgraph')
        days: Number of days of history to retrieve (default: 90)

    Returns:
        Historical snapshots with metrics over time
    """
    client = get_elastic_agent_client()

    try:
        result = client.invoke_tool(
            "get-trend-data",
            {
                "repo_name": repo_name,
                "start_date": days_ago_iso(days),
            }
        )
        return result

    except ElasticAgentError as e:
        logger.error(f"Trend data retrieval failed: {e}")
        return {"error": str(e), "results": []}


@tool
def get_repository_timeseries(repo_name: str, days: int = 180) -> dict:
    """
    Get detailed time-series metrics for trend visualization.

    Returns granular metrics including stars, forks, commits,
    issue close rates, and PR merge rates over time.

    Args:
        repo_name: Full repository name
        days: Number of days of history (default: 180)

    Returns:
        Time-series data points for visualization
    """
    client = get_elastic_agent_client()

    try:
        result = client.invoke_tool(
            "get-repo-timeseries",
            {
                "repo_name": repo_name,
                "start_date": days_ago_iso(days),
            }
        )
        return result

    except ElasticAgentError as e:
        logger.error(f"Time-series retrieval failed: {e}")
        return {"error": str(e), "results": []}


@tool
def get_repository_stats(repo_name: str, days: int = 90) -> dict:
    """
    Get aggregated statistics for a repository's metrics.

    Returns averages, min/max values, and counts for key metrics.

    Args:
        repo_name: Full repository name
        days: Number of days to analyze (default: 90)

    Returns:
        Aggregated statistics (avg_stars, max_stars, etc.)
    """
    client = get_elastic_agent_client()

    try:
        result = client.invoke_tool(
            "get-repo-timeseries-stats",
            {
                "repo_name": repo_name,
                "start_date": days_ago_iso(days),
            }
        )
        return result

    except ElasticAgentError as e:
        logger.error(f"Stats retrieval failed: {e}")
        return {"error": str(e), "results": []}


# =============================================================================
# Comparison & Snapshot Tools
# =============================================================================

@tool
def get_latest_snapshot(repo_name: str) -> dict:
    """
    Get the most recent research snapshot for a repository.

    Useful for comparisons - returns the latest metrics and analysis.

    Args:
        repo_name: Full repository name

    Returns:
        Latest snapshot with metrics, viability score, and risk flags
    """
    client = get_elastic_agent_client()

    try:
        result = client.invoke_tool(
            "get-latest-snapshot",
            {"repo_name": repo_name}
        )
        return result

    except ElasticAgentError as e:
        logger.error(f"Snapshot retrieval failed: {e}")
        return {"error": str(e), "results": []}


# =============================================================================
# Adoption Signal Tools
# =============================================================================

@tool
def get_adoption_signals(repo_name: str, days: int = 90) -> dict:
    """
    Get adoption signals for a repository.

    Retrieves blog posts, case studies, conference talks, and job
    postings that mention the technology.

    Args:
        repo_name: Full repository name
        days: Number of days of history (default: 90)

    Returns:
        Adoption signals with sources, types, and sentiment
    """
    client = get_elastic_agent_client()

    try:
        result = client.invoke_tool(
            "get-adoption-signals",
            {
                "repo_name": repo_name,
                "start_date": days_ago_iso(days),
            }
        )
        return result

    except ElasticAgentError as e:
        logger.error(f"Adoption signals retrieval failed: {e}")
        return {"error": str(e), "results": []}


@tool
def get_adoption_signals_by_type(
    repo_name: str,
    signal_type: str,
    days: int = 90
) -> dict:
    """
    Get adoption signals filtered by type.

    Args:
        repo_name: Full repository name
        signal_type: Type of signal ('blog_post', 'case_study',
                    'conference_talk', or 'job_posting')
        days: Number of days of history (default: 90)

    Returns:
        Filtered adoption signals
    """
    client = get_elastic_agent_client()

    try:
        result = client.invoke_tool(
            "get-adoption-signals-by-type",
            {
                "repo_name": repo_name,
                "signal_type": signal_type,
                "start_date": days_ago_iso(days),
            }
        )
        return result

    except ElasticAgentError as e:
        logger.error(f"Adoption signals by type retrieval failed: {e}")
        return {"error": str(e), "results": []}


@tool
def count_adoption_signals(repo_name: str, days: int = 90) -> dict:
    """
    Count adoption signals by type for a repository.

    Args:
        repo_name: Full repository name
        days: Number of days of history (default: 90)

    Returns:
        Counts grouped by signal type
    """
    client = get_elastic_agent_client()

    try:
        result = client.invoke_tool(
            "count-adoption-signals",
            {
                "repo_name": repo_name,
                "start_date": days_ago_iso(days),
            }
        )
        return result

    except ElasticAgentError as e:
        logger.error(f"Signal count failed: {e}")
        return {"error": str(e), "results": []}


# =============================================================================
# Research Report Tools
# =============================================================================

@tool
def get_latest_research_report(repo_name: str) -> dict:
    """
    Get the most recent research report for a repository.

    Args:
        repo_name: Full repository name

    Returns:
        Latest report with scores, recommendations, and full content
    """
    client = get_elastic_agent_client()

    try:
        result = client.invoke_tool(
            "get-latest-report",
            {"repo_name": repo_name}
        )
        return result

    except ElasticAgentError as e:
        logger.error(f"Report retrieval failed: {e}")
        return {"error": str(e), "results": []}


@tool
def get_cached_research_report(repo_name: str, max_age_days: int = 7) -> dict:
    """
    Get a cached research report if available within age limit.

    Use this to check for recent reports before running a new evaluation.

    Args:
        repo_name: Full repository name
        max_age_days: Maximum age of report in days (default: 7)

    Returns:
        Cached report if found, empty results if not
    """
    client = get_elastic_agent_client()

    try:
        result = client.invoke_tool(
            "get-cached-report",
            {
                "repo_name": repo_name,
                "min_timestamp": days_ago_iso(max_age_days),
            }
        )
        return result

    except ElasticAgentError as e:
        logger.error(f"Cached report retrieval failed: {e}")
        return {"error": str(e), "results": []}


# =============================================================================
# Cache Tools
# =============================================================================

@tool
def check_search_cache(query_hash: str, max_age_days: int = 7) -> dict:
    """
    Check if cached search results exist for a query.

    Args:
        query_hash: SHA256 hash of the search query (first 16 chars)
        max_age_days: Maximum age of cache in days (default: 7)

    Returns:
        Cached results if found
    """
    client = get_elastic_agent_client()

    try:
        result = client.invoke_tool(
            "get-cached-search",
            {
                "query_hash": query_hash,
                "min_timestamp": days_ago_iso(max_age_days),
            }
        )
        return result

    except ElasticAgentError as e:
        logger.error(f"Cache check failed: {e}")
        return {"error": str(e), "results": []}


@tool
def check_github_metrics_cache(repo_name: str, max_age_hours: int = 24) -> dict:
    """
    Check if cached GitHub metrics exist for a repository.

    Args:
        repo_name: Full repository name
        max_age_hours: Maximum age of cache in hours (default: 24)

    Returns:
        Cached metrics if found
    """
    client = get_elastic_agent_client()

    try:
        result = client.invoke_tool(
            "get-cached-github-metrics",
            {
                "repo_name": repo_name,
                "min_timestamp": hours_ago_iso(max_age_hours),
            }
        )
        return result

    except ElasticAgentError as e:
        logger.error(f"Metrics cache check failed: {e}")
        return {"error": str(e), "results": []}


# =============================================================================
# Discovery Tools
# =============================================================================

@tool
def get_past_discoveries(days: int = 90) -> dict:
    """
    Get past technology discovery results.

    Args:
        days: Number of days of history (default: 90)

    Returns:
        Past discoveries with use cases and technologies found
    """
    client = get_elastic_agent_client()

    try:
        result = client.invoke_tool(
            "get-past-discoveries",
            {"start_date": days_ago_iso(days)}
        )
        return result

    except ElasticAgentError as e:
        logger.error(f"Discoveries retrieval failed: {e}")
        return {"error": str(e), "results": []}


@tool
def search_discoveries_by_use_case(
    use_case_pattern: str,
    days: int = 90
) -> dict:
    """
    Search past discoveries by use case description.

    Args:
        use_case_pattern: Pattern to search (use wildcards like '*agent*')
        days: Number of days of history (default: 90)

    Returns:
        Matching discoveries
    """
    client = get_elastic_agent_client()

    try:
        result = client.invoke_tool(
            "search-discoveries-by-use-case",
            {
                "use_case_pattern": use_case_pattern,
                "start_date": days_ago_iso(days),
            }
        )
        return result

    except ElasticAgentError as e:
        logger.error(f"Discovery search failed: {e}")
        return {"error": str(e), "results": []}


@tool
def get_all_discovered_repositories() -> dict:
    """
    Get all repositories from past technology discoveries.

    Returns:
        All discovered repositories with timestamps
    """
    client = get_elastic_agent_client()

    try:
        result = client.invoke_tool(
            "get-all-discovered-repos",
            {}
        )
        return result

    except ElasticAgentError as e:
        logger.error(f"All discoveries retrieval failed: {e}")
        return {"error": str(e), "results": []}


# =============================================================================
# Export all tools
# =============================================================================

ELASTIC_SUBAGENT_TOOLS = [
    # Semantic Search
    semantic_search_technologies,
    search_technologies_by_tags,
    # Trends & History
    get_repository_trends,
    get_repository_timeseries,
    get_repository_stats,
    # Comparison
    get_latest_snapshot,
    # Adoption Signals
    get_adoption_signals,
    get_adoption_signals_by_type,
    count_adoption_signals,
    # Reports
    get_latest_research_report,
    get_cached_research_report,
    # Cache
    check_search_cache,
    check_github_metrics_cache,
    # Discoveries
    get_past_discoveries,
    search_discoveries_by_use_case,
    get_all_discovered_repositories,
]
