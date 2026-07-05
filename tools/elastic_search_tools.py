"""
Elastic search tools for the elastic-agent subagent.

These are thin @tool wrappers around the direct-Elasticsearch retrieval helpers
in `elasticsearch_tools.py`. They let the elastic-agent subagent query
Elasticsearch itself — no round-trip through the Elastic Agent Builder /converse
endpoint. Every tool returns structured JSON-serializable data (dicts/lists) so
the agent reasons over real values rather than re-parsing prose.

The underlying plain functions are kept as-is (they are imported and called
directly elsewhere, e.g. cli.py), so these wrappers only add the @tool surface.

The remaining retrieval tools the subagent uses are already @tool-decorated in
elasticsearch_tools.py: find_similar_technologies, get_trend_data,
search_by_tags, compare_technologies.
"""

from typing import Optional

from langchain_core.tools import tool

from .elasticsearch_tools import (
    get_repo_timeseries as _get_repo_timeseries,
    get_adoption_signals as _get_adoption_signals,
    get_latest_report as _get_latest_report,
    get_cached_report as _get_cached_report,
    get_past_discoveries as _get_past_discoveries,
    get_all_discovered_repos as _get_all_discovered_repos,
)


@tool
def search_repo_timeseries(repo: str, days: int = 180) -> list:
    """
    Get point-in-time metrics snapshots for a repository from the repo-timeseries
    index, for building trend graphs (stars, forks, issues, commit velocity, rates).

    Args:
        repo: Full repository name (e.g., "langchain-ai/langgraph")
        days: How many days of history to retrieve (default 180)

    Returns:
        A list of snapshot dicts sorted oldest-to-newest. Empty list if none found.
    """
    return _get_repo_timeseries(repo, days=days)


@tool
def search_adoption_signals(
    repo: str, signal_type: Optional[str] = None, days: int = 90
) -> list:
    """
    Get web-sourced adoption signals for a repository from the adoption-signals
    index (blog posts, case studies, conference talks, job postings, tutorials).

    Args:
        repo: Full repository name (e.g., "elastic/kibana")
        signal_type: Optional filter — one of blog_post, case_study,
                     conference_talk, job_posting, tutorial, criticism.
                     Omit to get all types.
        days: How many days of history to retrieve (default 90)

    Returns:
        A list of adoption-signal dicts, newest first. Empty list if none found.
    """
    return _get_adoption_signals(repo, signal_type=signal_type, days=days)


@tool
def fetch_latest_report(repo: str) -> dict:
    """
    Get the most recent research report for a repository from the research-reports
    index, regardless of age. Use to retrieve prior evaluation/comparison findings.

    Args:
        repo: Full repository name (e.g., "crewAIInc/crewAI")

    Returns:
        The latest report dict, or {"found": False, "repo": repo} if none exists.
    """
    report = _get_latest_report(repo)
    return report if report is not None else {"found": False, "repo": repo}


@tool
def fetch_cached_report(repo: str, max_age_days: int = 7) -> dict:
    """
    Get a recent research report for a repository ONLY if one exists within the
    given age window. Use this to decide whether fresh research is needed or a
    recent report can be reused (cost/time savings).

    Args:
        repo: Full repository name (e.g., "microsoft/autogen")
        max_age_days: Maximum age in days for the report to count as fresh (default 7)

    Returns:
        The report dict if a fresh one exists, otherwise
        {"found": False, "repo": repo, "max_age_days": max_age_days}.
    """
    report = _get_cached_report(repo, max_age_days=max_age_days)
    if report is not None:
        return report
    return {"found": False, "repo": repo, "max_age_days": max_age_days}


@tool
def search_past_discoveries(use_case: Optional[str] = None, days: int = 90) -> list:
    """
    Get past technology-discovery runs from the technology-discoveries index.
    Optionally filter by use case to find prior discoveries for similar goals.

    Args:
        use_case: Optional natural-language use case to match (fuzzy). Omit to get
                  all recent discoveries.
        days: How many days of history to retrieve (default 90)

    Returns:
        A list of discovery dicts, newest first. Empty list if none found.
    """
    return _get_past_discoveries(use_case=use_case, days=days)


@tool
def list_discovered_repos() -> list:
    """
    List every unique repository GitHub URL seen across all past technology
    discoveries. Useful for knowing what has already been researched.

    Returns:
        A list of unique GitHub repo URLs. Empty list if none found.
    """
    return _get_all_discovered_repos()


# The read-only tools contributed by this module.
ELASTIC_WRAPPER_TOOLS = [
    search_repo_timeseries,
    search_adoption_signals,
    fetch_latest_report,
    fetch_cached_report,
    search_past_discoveries,
    list_discovered_repos,
]
