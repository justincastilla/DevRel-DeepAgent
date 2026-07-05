"""
Tools for the DevRel Research Agent.
"""

from .github_tools import (
    fetch_repo_metrics,
    fetch_recent_issues,
    fetch_repo_discussions,
    fetch_repo_info_from_web,  # Web fallback for SAML-blocked repos
    # Connection pool management
    get_github_client,
    close_github_client,
    # Rate limiting
    RateLimiter,
    get_rate_limiter,
    get_remaining_github_calls,
    get_github_rate_limit_stats,
)
from .cache import (
    get_cached_search,
    store_search_cache,
    get_cached_github_metrics,
    store_github_metrics_cache,
    get_cached_github_data,
    store_github_data_cache,
)
from .elasticsearch_tools import (
    store_research_snapshot,
    find_similar_technologies,
    get_trend_data,
    compare_technologies,
    search_by_tags,
    # Time-series functions
    store_timeseries_snapshot,
    store_commit_history,
    get_repo_timeseries,
    # Adoption signals functions
    store_adoption_signal,
    get_adoption_signals,
    # Research reports functions
    store_research_report,
    get_latest_report,
    get_cached_report,
    # Discovery functions
    store_discovery,
    get_past_discoveries,
    get_all_discovered_repos,
)
from .scoring_tools import calculate_viability_score
from .web_tools import tavily_search, record_adoption_signal

# Direct-Elasticsearch @tool wrappers used by the elastic-agent subagent.
from .elastic_search_tools import (
    search_repo_timeseries,
    search_adoption_signals,
    fetch_latest_report,
    fetch_cached_report,
    search_past_discoveries,
    list_discovered_repos,
    ELASTIC_WRAPPER_TOOLS,
)

# Legacy Elastic Agent Builder client & /converse tool. Kept dormant — the
# elastic-agent subagent now queries Elasticsearch directly (see
# tools/elastic_search_tools.py and subagents/elastic_agent.py). Retained for
# fallback/reference only; no longer wired into the agent.
from .elastic_agent_client import (
    ElasticAgentClient,
    ElasticAgentError,
    get_elastic_agent_client,
    days_ago_iso,
    hours_ago_iso,
)
from .elastic_subagent_tools import ask_elastic_agent

__all__ = [
    # GitHub tools
    "fetch_repo_metrics",
    "fetch_recent_issues",
    "fetch_repo_discussions",
    "get_github_client",
    "close_github_client",
    # Elasticsearch tools
    "store_research_snapshot",
    "find_similar_technologies",
    "get_trend_data",
    "compare_technologies",
    "search_by_tags",
    # Cache functions
    "get_cached_search",
    "store_search_cache",
    "get_cached_github_metrics",
    "store_github_metrics_cache",
    "get_cached_github_data",
    "store_github_data_cache",
    # Time-series functions
    "store_timeseries_snapshot",
    "store_commit_history",
    "get_repo_timeseries",
    # Adoption signals functions
    "store_adoption_signal",
    "get_adoption_signals",
    # Research reports functions
    "store_research_report",
    "get_latest_report",
    "get_cached_report",
    # Discovery functions
    "store_discovery",
    "get_past_discoveries",
    "get_all_discovered_repos",
    # Scoring tools
    "calculate_viability_score",
    # Web search tools
    "tavily_search",
    "record_adoption_signal",
    # Direct-Elasticsearch @tool wrappers (elastic-agent subagent)
    "search_repo_timeseries",
    "search_adoption_signals",
    "fetch_latest_report",
    "fetch_cached_report",
    "search_past_discoveries",
    "list_discovered_repos",
    "ELASTIC_WRAPPER_TOOLS",
    # Legacy Elastic Agent Builder client & tool (dormant)
    "ElasticAgentClient",
    "ElasticAgentError",
    "get_elastic_agent_client",
    "days_ago_iso",
    "hours_ago_iso",
    "ask_elastic_agent",
]
