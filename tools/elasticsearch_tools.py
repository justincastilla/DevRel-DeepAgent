"""
Elasticsearch tools for storing and querying technology research data.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from elasticsearch import Elasticsearch
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from config import config
from exceptions import ElasticsearchError
from tools.redis_cache import cache_get, cache_set
from utils.logging_utils import get_logger

logger = get_logger(__name__)


# =============================================================================
# Typed input models for store_research_snapshot
# These are included in the tool schema sent to the LLM, constraining which
# fields are valid and preventing invented keys like "date_range".
# =============================================================================

class SnapshotMetrics(BaseModel):
    """Raw GitHub repository counts. All fields are integers."""
    stars: int = Field(description="Total star count")
    forks: int = Field(description="Total fork count")
    open_issues: int = Field(description="Number of currently open issues")
    closed_issues: int = Field(description="Number of closed issues")
    open_prs: int = Field(description="Number of currently open pull requests")
    merged_prs: int = Field(description="Number of merged pull requests")
    contributors: int = Field(description="Total contributor count")


class SnapshotDerived(BaseModel):
    """Derived activity and velocity metrics computed from raw GitHub data."""
    repo_age_days: Optional[int] = Field(None, description="Repository age in days")
    stars_per_month: Optional[float] = Field(None, description="Average new stars per month")
    commits_7d: Optional[int] = Field(None, description="Commits in the last 7 days")
    commits_30d: Optional[int] = Field(None, description="Commits in the last 30 days")
    commits_90d: Optional[int] = Field(None, description="Commits in the last 90 days")
    unique_authors_7d: Optional[int] = Field(None, description="Unique committers in last 7 days")
    unique_authors_30d: Optional[int] = Field(None, description="Unique committers in last 30 days")
    issue_close_rate: Optional[float] = Field(None, description="Fraction of issues closed (0.0–1.0)")
    pr_merge_rate: Optional[float] = Field(None, description="Fraction of PRs merged (0.0–1.0)")


class SnapshotAnalysis(BaseModel):
    """Scored analysis results from the research run."""
    viability_score: float = Field(description="Overall viability score 0–100")
    health_score: float = Field(description="Repository health component 0–40")
    community_score: float = Field(description="Community health component 0–30")
    adoption_score: float = Field(description="Adoption signal component 0–30")
    sentiment_score: Optional[float] = Field(None, description="Community sentiment score 0–100")
    risk_flags: list[str] = Field(default_factory=list, description="Identified risk factors")
    recommendation: str = Field(description="Coverage recommendation: COVER, WATCH, or SKIP")
    summary: str = Field(description="2–3 sentence plain-text research summary")


# Module-level singleton. Building an Elasticsearch() object opens a connection
# pool and (for https) does a TLS handshake, so we reuse one client for the
# whole process instead of creating a new one on every call.
_es_client: Optional[Elasticsearch] = None


def get_es_client() -> Elasticsearch:
    """
    Get the shared Elasticsearch client, creating it on first use.

    Returns:
        Configured Elasticsearch client instance

    Raises:
        ElasticsearchError: If connection cannot be established
    """
    global _es_client
    if _es_client is None:
        if not config.ELASTICSEARCH_URL or not config.ELASTICSEARCH_API_KEY:
            raise ElasticsearchError("Elasticsearch credentials not configured")
        try:
            _es_client = Elasticsearch(
                config.ELASTICSEARCH_URL,
                api_key=config.ELASTICSEARCH_API_KEY,
            )
        except Exception as e:
            logger.error(f"Failed to connect to Elasticsearch: {e}")
            raise ElasticsearchError(f"Failed to connect to Elasticsearch: {e}") from e
    return _es_client


def sanitize_metrics_for_es(metrics: dict) -> dict:
    """
    Sanitize metrics dict for Elasticsearch storage.

    The 'technology-research' index maps known metric fields as integers.
    Any extra fields the LLM adds (e.g. date_range, commit_velocity) may
    collide with a previously auto-mapped type.  Convert nested dicts/lists
    to JSON strings so the document is always storable.
    """
    KNOWN_INT_FIELDS = {
        "stars", "forks", "open_issues", "closed_issues",
        "open_prs", "merged_prs", "contributors",
    }
    sanitized = {}
    for key, value in metrics.items():
        if key in KNOWN_INT_FIELDS:
            try:
                sanitized[key] = int(value) if value is not None else 0
            except (TypeError, ValueError):
                sanitized[key] = 0
        elif isinstance(value, (dict, list)):
            sanitized[key] = json.dumps(value) if value else ""
        else:
            sanitized[key] = value
    return sanitized


def sanitize_analysis_for_es(analysis: dict) -> dict:
    """
    Sanitize analysis dict to match Elasticsearch mapping.
    Ensures fields match their expected types in the ES schema.
    """
    SCALAR_FIELDS = {
        "viability_score", "health_score", "community_score",
        "adoption_score", "sentiment_score", "summary"
    }
    KEYWORD_FIELDS = {"recommendation"}  # Must be simple strings
    ARRAY_FIELDS = {"risk_flags"}
    # Fields that must be objects with specific structure
    OBJECT_FIELDS = {"recommendation_details"}

    sanitized = {}
    for key, value in analysis.items():
        if key in KEYWORD_FIELDS:
            # Keywords must be simple strings - convert objects to JSON
            if isinstance(value, dict):
                # Try to extract a status/recommendation string, or stringify
                sanitized[key] = value.get("status", value.get("recommendation", json.dumps(value)))
            elif isinstance(value, list):
                sanitized[key] = ", ".join(str(v) for v in value)
            else:
                sanitized[key] = str(value) if value else ""

        elif key in OBJECT_FIELDS:
            # Must be an object with use_if/avoid_if arrays
            if isinstance(value, dict):
                sanitized[key] = {
                    "use_if": value.get("use_if", []),
                    "avoid_if": value.get("avoid_if", []),
                }
            elif isinstance(value, str) and value:
                # String provided - put it in use_if
                sanitized[key] = {
                    "use_if": [value],
                    "avoid_if": [],
                }
            else:
                # Skip if empty/None - don't include the field
                pass

        elif key in SCALAR_FIELDS:
            # Scalars - convert objects to JSON strings
            if isinstance(value, (dict, list)):
                sanitized[key] = json.dumps(value) if value else ""
            else:
                sanitized[key] = value

        elif key in ARRAY_FIELDS:
            # Arrays of keywords
            if isinstance(value, list):
                # Flatten any nested objects to strings
                sanitized[key] = [str(v) if isinstance(v, dict) else v for v in value]
            else:
                sanitized[key] = [str(value)] if value else []

        elif isinstance(value, (dict, list)):
            # Unknown fields with complex values - convert to JSON string
            sanitized[key] = json.dumps(value) if value else ""
        else:
            sanitized[key] = value

    return sanitized


@tool
def store_research_snapshot(
    repo_name: str,
    metrics: SnapshotMetrics,
    analysis: SnapshotAnalysis,
    derived: Optional[SnapshotDerived] = None,
    tags: Optional[list[str]] = None,
) -> str:
    """
    Store a point-in-time research snapshot in Elasticsearch.
    Enables trend analysis and historical comparison over time.

    Args:
        repo_name: Full repository name (e.g., "langchain-ai/deepagents")
        metrics: Raw GitHub counts — stars, forks, issues, PRs, contributors
        analysis: Scored analysis results — viability, health, community, adoption scores
        derived: Optional velocity metrics — commits_30d, issue_close_rate, etc.
        tags: Optional tags for categorization (e.g., ["ai-agents", "python"])

    Returns:
        Confirmation message with document ID
    """
    logger.info(f"Storing research snapshot for {repo_name}")

    try:
        es = get_es_client()

        # Convert Pydantic models to dicts (sanitizers handle type coercion as a safety net)
        metrics_dict = metrics.model_dump()
        analysis_dict = analysis.model_dump()

        sanitized_metrics = sanitize_metrics_for_es(metrics_dict)
        sanitized_analysis = sanitize_analysis_for_es(analysis_dict)

        # Create searchable text for embedding
        summary_text = f"{repo_name} {sanitized_analysis.get('summary', '')} {' '.join(tags or [])}"

        doc = {
            "repo": repo_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": sanitized_metrics,
            "analysis": sanitized_analysis,
            "tags": tags or [],
            "semantic_content": summary_text,
        }

        if derived:
            doc["derived"] = derived.model_dump(exclude_none=True)

        result = es.index(index="technology-research", document=doc)
        logger.info(f"Stored snapshot for {repo_name} with ID: {result['_id']}")
        return f"Stored snapshot for {repo_name} with ID: {result['_id']}"
    except Exception as e:
        logger.error(f"Failed to store snapshot for {repo_name}: {e}")
        raise ElasticsearchError(f"Failed to store snapshot: {e}") from e


@tool
def find_similar_technologies(description: str, limit: int = 5) -> list:
    """
    Use vector search to find similar technologies in our research history.
    Great for discovering alternatives or related frameworks.

    Args:
        description: Natural language description of what you're looking for
        limit: Maximum number of results to return (default 5)

    Returns:
        List of similar technologies with their metrics and analysis
    """
    logger.info(f"Finding similar technologies for: {description}")

    try:
        es = get_es_client()

        results = es.search(
            index="technology-research",
            query={
                "semantic": {
                    "field": "semantic_content",
                    "query": description
                }
            },
            size=limit,
            source=["repo", "timestamp", "metrics", "analysis", "tags"],
        )

        similar_tech = [
            {
                "repo": hit["_source"]["repo"],
                "timestamp": hit["_source"]["timestamp"],
                "metrics": hit["_source"].get("metrics", {}),
                "analysis": hit["_source"].get("analysis", {}),
                "tags": hit["_source"].get("tags", []),
                "similarity_score": hit["_score"],
            }
            for hit in results["hits"]["hits"]
        ]

        logger.info(f"Found {len(similar_tech)} similar technologies")
        return similar_tech
    except Exception as e:
        logger.error(f"Failed to find similar technologies: {e}")
        raise ElasticsearchError(f"Failed to find similar technologies: {e}") from e


@tool
def get_trend_data(repo_name: str, days: int = 90) -> dict:
    """
    Query historical snapshots to identify trends for a specific repository.
    Shows changes in stars, issues, commit velocity over time.

    Args:
        repo_name: Full repository name
        days: Number of days to look back (default 90)

    Returns:
        Trend data including data points and calculated changes
    """
    logger.info(f"Getting trend data for {repo_name} over {days} days")

    try:
        es = get_es_client()

        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        results = es.search(
            index="technology-research",
            query={
                "bool": {
                    "must": [
                        {"term": {"repo": repo_name}},
                        {"range": {"timestamp": {"gte": since}}},
                    ]
                }
            },
            sort=[{"timestamp": "asc"}],
            size=100,
        )

        snapshots = [hit["_source"] for hit in results["hits"]["hits"]]

        if len(snapshots) < 2:
            return {
                "repo": repo_name,
                "message": "Insufficient historical data for trend analysis",
                "snapshots_found": len(snapshots),
            }

        # Calculate trends
        first = snapshots[0]
        last = snapshots[-1]

        first_metrics = first.get("metrics", {})
        last_metrics = last.get("metrics", {})

        trend_data = {
            "repo": repo_name,
            "period": f"{days} days",
            "snapshots_analyzed": len(snapshots),
            "trends": {
                "stars": {
                    "start": first_metrics.get("stars", 0),
                    "end": last_metrics.get("stars", 0),
                    "change": last_metrics.get("stars", 0) - first_metrics.get("stars", 0),
                },
                "open_issues": {
                    "start": first_metrics.get("open_issues", 0),
                    "end": last_metrics.get("open_issues", 0),
                    "change": last_metrics.get("open_issues", 0) - first_metrics.get("open_issues", 0),
                },
                "viability_score": {
                    "start": first.get("analysis", {}).get("viability_score", 0),
                    "end": last.get("analysis", {}).get("viability_score", 0),
                    "change": (
                        last.get("analysis", {}).get("viability_score", 0) -
                        first.get("analysis", {}).get("viability_score", 0)
                    ),
                },
            },
            "first_snapshot": first["timestamp"],
            "last_snapshot": last["timestamp"],
        }

        logger.info(f"Retrieved trend data for {repo_name}")
        return trend_data
    except Exception as e:
        logger.error(f"Failed to get trend data for {repo_name}: {e}")
        raise ElasticsearchError(f"Failed to get trend data: {e}") from e


@tool
def compare_technologies(repos: list[str]) -> dict:
    """
    Run aggregations to compare multiple technologies side-by-side.
    Uses the most recent snapshot for each repository.

    Args:
        repos: List of repository names to compare (e.g., ["langchain-ai/deepagents", "microsoft/autogen"])

    Returns:
        Comparison table with metrics for each repository
    """
    logger.info(f"Comparing technologies: {repos}")

    try:
        es = get_es_client()

        comparisons = []

        for repo in repos:
            # Get most recent snapshot
            result = es.search(
                index="technology-research",
                query={"term": {"repo": repo}},
                sort=[{"timestamp": "desc"}],
                size=1,
            )

            if result["hits"]["hits"]:
                snapshot = result["hits"]["hits"][0]["_source"]
                metrics = snapshot.get("metrics", {})
                analysis = snapshot.get("analysis", {})

                comparisons.append({
                    "repo": repo,
                    "snapshot_date": snapshot["timestamp"],
                    "stars": metrics.get("stars", "N/A"),
                    "forks": metrics.get("forks", "N/A"),
                    "open_issues": metrics.get("open_issues", "N/A"),
                    "contributors": metrics.get("contributors", "N/A"),
                    "viability_score": analysis.get("viability_score", "N/A"),
                    "risk_flags": analysis.get("risk_flags", []),
                })
            else:
                comparisons.append({
                    "repo": repo,
                    "error": "No research data found",
                })

        result = {
            "comparison_date": datetime.now(timezone.utc).isoformat(),
            "repositories": comparisons,
        }

        logger.info(f"Compared {len(repos)} technologies")
        return result
    except Exception as e:
        logger.error(f"Failed to compare technologies: {e}")
        raise ElasticsearchError(f"Failed to compare technologies: {e}") from e


@tool
def search_by_tags(tags: list[str], min_viability: float = 0) -> list:
    """
    Search for technologies by tags with optional viability filter.

    Args:
        tags: List of tags to search for (e.g., ["ai-agents", "python"])
        min_viability: Minimum viability score filter (0-100)

    Returns:
        List of matching technologies sorted by viability score
    """
    logger.info(f"Searching by tags: {tags}, min viability: {min_viability}")

    try:
        es = get_es_client()

        query = {
            "bool": {
                "must": [
                    {"terms": {"tags": tags}},
                ],
                "filter": [
                    {"range": {"analysis.viability_score": {"gte": min_viability}}},
                ],
            }
        }

        # Get most recent snapshot per repo using collapse
        results = es.search(
            index="technology-research",
            query=query,
            collapse={"field": "repo"},
            sort=[
                {"analysis.viability_score": "desc"},
                {"timestamp": "desc"},
            ],
            size=20,
        )

        technologies = [
            {
                "repo": hit["_source"]["repo"],
                "viability_score": hit["_source"].get("analysis", {}).get("viability_score"),
                "tags": hit["_source"].get("tags", []),
                "summary": hit["_source"].get("analysis", {}).get("summary", ""),
            }
            for hit in results["hits"]["hits"]
        ]

        logger.info(f"Found {len(technologies)} technologies matching tags")
        return technologies
    except Exception as e:
        logger.error(f"Failed to search by tags: {e}")
        raise ElasticsearchError(f"Failed to search by tags: {e}") from e


# =============================================================================
# CACHING FUNCTIONS - Fast key/value caching backed by a local Redis instance
#
# These used to store cache documents in Elasticsearch. They now use Redis (see
# tools/redis_cache.py). Redis expires stale entries itself via TTL, so there is
# no cleanup job to run, and a lookup is a single GET instead of a search query.
#
# The max_age_* arguments are kept so existing callers don't need to change, but
# freshness is now governed by the TTL set when the entry was written (the
# CACHE_TTL_* values in config.py). If Redis is down these degrade gracefully:
# reads act as a miss, writes are skipped.
# =============================================================================

def _hash_query(query: str) -> str:
    """Generate a stable short hash for a search query (used in the cache key)."""
    return hashlib.sha256(query.lower().strip().encode()).hexdigest()[:16]


def get_cached_search(query: str, max_age_days: int = 7) -> Optional[dict]:
    """
    Return cached web-search results for a query, or None on a miss.

    Args:
        query: The search query
        max_age_days: Retained for backwards compatibility (Redis TTL governs freshness)

    Returns:
        Cached results if present, None otherwise
    """
    key = f"websearch:{_hash_query(query)}"
    cached = cache_get(key)
    if cached is not None:
        logger.info(f"Cache HIT for query: {query[:50]}...")
        return cached

    logger.info(f"Cache MISS for query: {query[:50]}...")
    return None


def store_search_cache(query: str, results: dict, search_type: str = "tavily") -> None:
    """
    Store web-search results in Redis with the web-search TTL.

    Args:
        query: The search query
        results: The search results to cache
        search_type: Type of search (kept for backwards compatibility)
    """
    key = f"websearch:{_hash_query(query)}"
    cache_set(key, results, config.CACHE_TTL_WEB_SEARCH)
    logger.info(f"Cached search results for: {query[:50]}...")


def get_cached_github_metrics(repo: str, max_age_hours: int = 24) -> Optional[dict]:
    """
    Return cached GitHub metrics for a repository, or None on a miss.

    Args:
        repo: Repository name (owner/repo)
        max_age_hours: Retained for backwards compatibility (Redis TTL governs freshness)

    Returns:
        Cached metrics if present, None otherwise
    """
    key = f"ghmetrics:{repo}"
    cached = cache_get(key)
    if cached is None:
        logger.info(f"GitHub cache MISS for {repo}")
        return None

    logger.info(f"GitHub cache HIT for {repo}")
    metrics = cached.get("metrics", {})
    derived = cached.get("derived", {})

    # Some cache entries store raw counts but not rates. Compute the rates here
    # so downstream scoring always gets correct values.
    if derived.get("issue_close_rate", 0) == 0:
        open_i = metrics.get("open_issues", 0)
        closed_i = metrics.get("closed_issues", 0)
        total_i = open_i + closed_i
        if total_i > 0:
            derived["issue_close_rate"] = round(closed_i / total_i * 100, 1)

    if derived.get("pr_merge_rate", 0) == 0:
        open_p = metrics.get("open_prs", 0)
        merged_p = metrics.get("merged_prs", 0)
        total_p = open_p + merged_p
        if total_p > 0:
            derived["pr_merge_rate"] = round(merged_p / total_p * 100, 1)

    return {
        "metrics": metrics,
        "derived": derived,
        "cached": True,
        "cache_timestamp": cached.get("cache_timestamp"),
    }


def store_github_metrics_cache(repo: str, metrics: dict, derived: dict = None) -> None:
    """
    Store GitHub metrics in Redis with the GitHub-metrics TTL.

    Args:
        repo: Repository name (owner/repo)
        metrics: Raw metrics from GitHub API
        derived: Derived calculations
    """
    key = f"ghmetrics:{repo}"
    value = {
        "repo": repo,
        "cache_timestamp": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
        "derived": derived or {},
    }
    cache_set(key, value, config.CACHE_TTL_GITHUB_METRICS)
    logger.info(f"Cached GitHub metrics for {repo}")


def get_cached_github_data(
    repo: str, data_type: str, max_age_hours: int = 8
) -> Optional[list]:
    """
    Return cached GitHub list data (issues or discussions) for a repo, or None.

    Args:
        repo: Repository name (owner/repo)
        data_type: 'issues' or 'discussions'
        max_age_hours: Retained for backwards compatibility (Redis TTL governs freshness)

    Returns:
        Cached list if present, None otherwise
    """
    key = f"ghdata:{repo}:{data_type}"
    cached = cache_get(key)
    if cached is not None:
        logger.info(f"GitHub {data_type} cache HIT for {repo} ({len(cached)} items)")
        return cached

    logger.info(f"GitHub {data_type} cache MISS for {repo}")
    return None


def store_github_data_cache(repo: str, data_type: str, data: list) -> None:
    """
    Store GitHub list data (issues or discussions) in Redis.

    Args:
        repo: Repository name (owner/repo)
        data_type: 'issues' or 'discussions'
        data: List of items to cache
    """
    key = f"ghdata:{repo}:{data_type}"
    cache_set(key, data, config.CACHE_TTL_GITHUB_DATA)
    logger.info(f"Cached {len(data)} {data_type} for {repo}")


# =============================================================================
# TIME-SERIES STORAGE - Build historical data for trend visualization
# =============================================================================

def store_timeseries_snapshot(repo: str, metrics: dict, derived: dict = None) -> None:
    """
    Store a point-in-time metrics snapshot for time-series analysis.
    Call this every time you fetch metrics to build up history.

    Args:
        repo: Repository name (owner/repo)
        metrics: Raw metrics dict with stars, forks, issues, etc.
        derived: Derived metrics like commits_30d, unique_authors, etc.
    """
    derived = derived or {}
    try:
        es = get_es_client()
        doc = {
            "repo": repo,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            # Core metrics
            "stars": metrics.get("stars", 0),
            "forks": metrics.get("forks", 0),
            "open_issues": metrics.get("open_issues", 0),
            "closed_issues": metrics.get("closed_issues", 0),
            "contributors": metrics.get("contributors", 0),
            "open_prs": metrics.get("open_prs", 0),
            "merged_prs": metrics.get("merged_prs", 0),
            # Activity metrics
            "commits_week": derived.get("commits_7d", derived.get("commits_week", 0)),
            "commits_month": derived.get("commits_30d", derived.get("commits_month", 0)),
            "unique_authors_week": derived.get("unique_authors_7d", 0),
            "unique_authors_month": derived.get("unique_authors_30d", 0),
            # Rates
            "issue_close_rate": derived.get("issue_close_rate", 0),
            "pr_merge_rate": derived.get("pr_merge_rate", 0),
            "stars_per_month": derived.get("stars_per_month", 0),
        }
        es.index(index="repo-timeseries", document=doc)
        logger.info(f"Stored timeseries snapshot for {repo}")
    except Exception as e:
        logger.warning(f"Failed to store timeseries snapshot: {e}")


def store_commit_history(repo: str, commits: list) -> None:
    """
    Store commit history data for detailed timeline analysis.
    Aggregates commits by week for efficient querying.

    Args:
        repo: Repository name (owner/repo)
        commits: List of commits with 'date' and 'author' fields
    """
    if not commits:
        return

    try:
        es = get_es_client()
        captured_at = datetime.now(timezone.utc).isoformat()

        # Aggregate commits by week
        weekly_data = {}
        for commit in commits:
            try:
                commit_date = datetime.fromisoformat(
                    commit["date"].replace("Z", "+00:00")
                ).replace(tzinfo=None)
                week_bucket = commit_date.strftime("%Y-W%W")
                author = commit.get("author", "unknown")

                key = (week_bucket, author)
                if key not in weekly_data:
                    weekly_data[key] = {
                        "week_bucket": week_bucket,
                        "author": author,
                        "commit_count": 0,
                        "first_commit": commit_date,
                    }
                weekly_data[key]["commit_count"] += 1
            except (ValueError, KeyError) as e:
                logger.debug(f"Skipping malformed commit: {e}")
                continue

        # Bulk index the weekly aggregates
        for (week_bucket, author), data in weekly_data.items():
            doc = {
                "repo": repo,
                "captured_at": captured_at,
                "commit_date": data["first_commit"].isoformat(),
                "week_bucket": week_bucket,
                "author": author,
                "commit_count": data["commit_count"],
            }
            es.index(index="commit-history", document=doc)

        logger.info(f"Stored {len(weekly_data)} weekly commit aggregates for {repo}")
    except Exception as e:
        logger.warning(f"Failed to store commit history: {e}")


def get_repo_timeseries(repo: str, days: int = 180) -> list:
    """
    Retrieve time-series data for a repository.

    Args:
        repo: Repository name (owner/repo)
        days: Number of days of history to retrieve

    Returns:
        List of snapshots sorted by timestamp
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    try:
        es = get_es_client()
        result = es.search(
            index="repo-timeseries",
            query={
                "bool": {
                    "must": [
                        {"term": {"repo": repo}},
                        {"range": {"timestamp": {"gte": since}}},
                    ]
                }
            },
            sort=[{"timestamp": "asc"}],
            size=1000,
        )
        return [hit["_source"] for hit in result["hits"]["hits"]]
    except Exception as e:
        logger.error(f"Failed to get timeseries for {repo}: {e}")
        return []


# =============================================================================
# ADOPTION SIGNALS STORAGE - Track web research findings
# =============================================================================

def store_adoption_signal(
    repo: str,
    signal_type: str,
    source_url: str,
    source_title: str,
    snippet: str = "",
    company_mentioned: str = None,
    use_case: str = None,
    sentiment: str = "neutral",
    search_query: str = None,
    relevance_score: float = None,
) -> None:
    """
    Store a structured adoption signal from web research.

    Args:
        repo: Repository name being researched
        signal_type: Type of signal (blog_post, case_study, conference_talk, job_posting)
        source_url: URL of the source
        source_title: Title of the article/post
        snippet: Relevant text excerpt
        company_mentioned: Company name if this is a case study
        use_case: Description of the use case
        sentiment: positive, neutral, or negative
        search_query: The query that found this result
        relevance_score: Tavily relevance score if available
    """
    try:
        es = get_es_client()

        # Extract domain from URL
        from urllib.parse import urlparse
        domain = urlparse(source_url).netloc if source_url else None

        doc = {
            "repo": repo,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "signal_type": signal_type,
            "source_url": source_url,
            "source_title": source_title,
            "source_domain": domain,
            "company_mentioned": company_mentioned,
            "use_case": use_case,
            "sentiment": sentiment,
            "snippet": snippet[:1000] if snippet else "",  # Truncate long snippets
            "search_query": search_query,
            "relevance_score": relevance_score,
        }
        es.index(index="adoption-signals", document=doc)
        logger.info(f"Stored {signal_type} signal for {repo}: {source_title[:50]}...")
    except Exception as e:
        logger.warning(f"Failed to store adoption signal: {e}")


def get_adoption_signals(repo: str, signal_type: str = None, days: int = 90) -> list:
    """
    Retrieve adoption signals for a repository.

    Args:
        repo: Repository name
        signal_type: Optional filter by signal type
        days: Number of days of history

    Returns:
        List of adoption signals
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    try:
        es = get_es_client()
        must_clauses = [
            {"term": {"repo": repo}},
            {"range": {"timestamp": {"gte": since}}},
        ]
        if signal_type:
            must_clauses.append({"term": {"signal_type": signal_type}})

        result = es.search(
            index="adoption-signals",
            query={"bool": {"must": must_clauses}},
            sort=[{"timestamp": "desc"}],
            size=100,
        )
        return [hit["_source"] for hit in result["hits"]["hits"]]
    except Exception as e:
        logger.error(f"Failed to get adoption signals for {repo}: {e}")
        return []


# =============================================================================
# RESEARCH REPORTS STORAGE - Store final analysis reports
# =============================================================================

@tool
def store_research_report(
    repo: str,
    report_type: str,
    full_report: str,
    viability_score: float = None,
    health_score: float = None,
    community_score: float = None,
    adoption_score: float = None,
    recommendation: str = None,
    risk_flags: list = None,
    strengths: str = None,
    concerns: str = None,
    summary: str = None,
    use_case: str = None,
    compared_repos: list = None,
) -> str:
    """
    Store a finalized research report for future reference.
    Use this after completing an evaluation or comparison.

    Args:
        repo: Primary repository being evaluated
        report_type: 'evaluation' or 'comparison'
        full_report: The complete markdown report
        viability_score: Overall viability score (0-100)
        health_score: Health component score
        community_score: Community component score
        adoption_score: Adoption component score
        recommendation: COVER, WATCH, or SKIP
        risk_flags: List of identified risks
        strengths: Key strengths summary
        concerns: Key concerns summary
        summary: Brief summary of findings
        use_case: The use case this was evaluated for
        compared_repos: List of repos if this is a comparison

    Returns:
        Confirmation message
    """
    try:
        es = get_es_client()
        doc = {
            "repo": repo,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "report_type": report_type,
            "use_case": use_case,
            "viability_score": viability_score,
            "health_score": health_score,
            "community_score": community_score,
            "adoption_score": adoption_score,
            "recommendation": recommendation,
            "risk_flags": risk_flags or [],
            "strengths": strengths,
            "concerns": concerns,
            "summary": summary,
            "full_report": full_report,
            "compared_repos": compared_repos or [],
        }
        result = es.index(index="research-reports", document=doc)
        logger.info(f"Stored research report for {repo} with ID: {result['_id']}")
        return f"Stored research report for {repo}"
    except Exception as e:
        logger.error(f"Failed to store research report: {e}")
        raise ElasticsearchError(f"Failed to store report: {e}") from e


def get_latest_report(repo: str) -> Optional[dict]:
    """
    Get the most recent research report for a repository.

    Args:
        repo: Repository name

    Returns:
        Latest report or None
    """
    try:
        es = get_es_client()
        result = es.search(
            index="research-reports",
            query={"term": {"repo": repo}},
            sort=[{"timestamp": "desc"}],
            size=1,
        )
        if result["hits"]["hits"]:
            return result["hits"]["hits"][0]["_source"]
        return None
    except Exception as e:
        logger.error(f"Failed to get latest report for {repo}: {e}")
        return None


def get_cached_report(repo: str, max_age_days: int = 7) -> Optional[dict]:
    """
    Get a recent research report if available (for cost savings).

    Args:
        repo: Repository name
        max_age_days: Maximum age of report to consider valid

    Returns:
        Recent report or None if stale/missing
    """
    since = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()

    try:
        es = get_es_client()
        result = es.search(
            index="research-reports",
            query={
                "bool": {
                    "must": [
                        {"term": {"repo": repo}},
                        {"range": {"timestamp": {"gte": since}}},
                    ]
                }
            },
            sort=[{"timestamp": "desc"}],
            size=1,
        )
        if result["hits"]["hits"]:
            report = result["hits"]["hits"][0]["_source"]
            logger.info(f"Found cached report for {repo} from {report['timestamp']}")
            return report
        return None
    except Exception as e:
        logger.warning(f"Failed to check for cached report: {e}")
        return None


# =============================================================================
# TECHNOLOGY DISCOVERY STORAGE - Track discovered technologies
# =============================================================================

def store_discovery(
    use_case: str,
    technologies: list,
    most_promising: str = None,
    full_report: str = None,
) -> str:
    """
    Store a technology discovery result.

    Args:
        use_case: The use case/description searched for
        technologies: List of discovered technologies, each with:
            - name: Technology name
            - github_url: GitHub repository URL
            - website_url: Website/docs URL (optional)
            - description: Brief description
            - relevance: Why it's relevant
            - stars: Star count (optional)
        most_promising: Name of most recommended technology
        full_report: Full markdown report

    Returns:
        Document ID
    """
    try:
        es = get_es_client()
        doc = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "use_case": use_case,
            "use_case_keyword": use_case.lower().strip(),
            "technologies": technologies,
            "technology_count": len(technologies),
            "most_promising": most_promising,
            "full_report": full_report,
        }
        result = es.index(index="technology-discoveries", document=doc)
        logger.info(f"Stored discovery for '{use_case}' with {len(technologies)} technologies")
        return result["_id"]
    except Exception as e:
        logger.error(f"Failed to store discovery: {e}")
        raise ElasticsearchError(f"Failed to store discovery: {e}") from e


def get_past_discoveries(use_case: str = None, days: int = 90) -> list:
    """
    Get past technology discoveries.

    Args:
        use_case: Optional filter by use case (fuzzy match)
        days: Number of days to look back

    Returns:
        List of past discoveries
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    try:
        es = get_es_client()

        if use_case:
            query = {
                "bool": {
                    "must": [
                        {"match": {"use_case": use_case}},
                        {"range": {"timestamp": {"gte": since}}},
                    ]
                }
            }
        else:
            query = {"range": {"timestamp": {"gte": since}}}

        result = es.search(
            index="technology-discoveries",
            query=query,
            sort=[{"timestamp": "desc"}],
            size=50,
        )
        return [hit["_source"] for hit in result["hits"]["hits"]]
    except Exception as e:
        logger.warning(f"Failed to get past discoveries: {e}")
        return []


def get_all_discovered_repos() -> list:
    """
    Get all unique repositories from past discoveries.
    Useful for building a knowledge base of known technologies.

    Returns:
        List of unique repo URLs discovered
    """
    try:
        es = get_es_client()
        result = es.search(
            index="technology-discoveries",
            query={"match_all": {}},
            size=1000,
        )

        repos = set()
        for hit in result["hits"]["hits"]:
            for tech in hit["_source"].get("technologies", []):
                if tech.get("github_url"):
                    repos.add(tech["github_url"])

        return list(repos)
    except Exception as e:
        logger.warning(f"Failed to get discovered repos: {e}")
        return []


# =============================================================================
# Cache Cleanup / Expiry
# =============================================================================
#
# There is intentionally no cleanup code here anymore. Caching now lives in
# Redis (see tools/redis_cache.py), and Redis expires stale keys automatically
# using the TTL set when each entry is written. The old cleanup_all_caches() /
# cleanup_cache_index() helpers and the scheduled cleanup workflow are no longer
# needed.
