"""Redis-backed cache for external API results.

This is the entire caching layer for the project. It replaces the three
Elasticsearch cache indices (web-search-cache, github-metrics-cache,
github-data-cache) plus their cleanup job.

Why Redis for caching?
    - Native per-key TTL: stale entries expire on their own, so there is no
      cleanup pass, no scheduled delete-by-query, and no timestamp math.
    - A cache is a simple key -> value store. Redis models that directly;
      Elasticsearch (a search engine) needed hand-written range queries.
    - Persistent, analytical data still lives in Elasticsearch. Only the
      ephemeral "avoid calling the API again" data lives here.

Graceful degradation: if REDIS_URL is unset or Redis is unreachable, every
function below behaves as a cache MISS and the app keeps working (just slower).
"""

import hashlib
import json
from typing import Optional

import redis

from config import config
from utils.logging_utils import get_logger

logger = get_logger(__name__)

# Lazy singleton client. decode_responses=True gives us str back instead of bytes.
_client: Optional[redis.Redis] = None


def _redis() -> Optional[redis.Redis]:
    """Return the shared Redis client, or None if caching is not configured."""
    global _client
    if _client is None and config.REDIS_URL:
        _client = redis.from_url(config.REDIS_URL, decode_responses=True)
    return _client


def _get(key: str) -> Optional[dict]:
    """Return the cached JSON value for a key, or None on miss/error."""
    client = _redis()
    if not client:
        return None
    try:
        raw = client.get(key)
    except Exception as e:  # never let a cache problem break the request
        logger.warning(f"Cache read failed for {key} (continuing without cache): {e}")
        return None
    return json.loads(raw) if raw else None


def _set(key: str, value: dict, ttl_seconds: int) -> None:
    """Store a JSON value under a key with a TTL. Redis expires it for us."""
    client = _redis()
    if not client:
        return
    try:
        client.set(key, json.dumps(value), ex=ttl_seconds)
    except Exception as e:
        logger.warning(f"Cache write failed for {key} (continuing): {e}")


def _hash_query(query: str) -> str:
    """Stable short hash of a search query, used as its cache key."""
    return hashlib.sha256(query.lower().strip().encode()).hexdigest()[:16]


# =============================================================================
# Web search cache (Tavily results)
# =============================================================================

def get_cached_search(query: str) -> Optional[dict]:
    """Return cached Tavily results for a query, or None."""
    results = _get(f"search:{_hash_query(query)}")
    if results is not None:
        logger.info(f"Cache HIT for search: {query[:50]}...")
    else:
        logger.info(f"Cache MISS for search: {query[:50]}...")
    return results


def store_search_cache(query: str, results: dict, ttl_days: int = 7) -> None:
    """Cache Tavily results for a query (default 7 days)."""
    _set(f"search:{_hash_query(query)}", results, ttl_days * 86400)
    logger.info(f"Cached search results for: {query[:50]}...")


# =============================================================================
# GitHub metrics cache (repo stars/issues/PRs + derived rates)
# =============================================================================

def get_cached_github_metrics(repo: str) -> Optional[dict]:
    """Return cached GitHub metrics for a repo as {"metrics", "derived"}, or None."""
    entry = _get(f"gh-metrics:{repo}")
    if entry is not None:
        logger.info(f"GitHub metrics cache HIT for {repo}")
    else:
        logger.info(f"GitHub metrics cache MISS for {repo}")
    return entry


def store_github_metrics_cache(
    repo: str, metrics: dict, derived: dict = None, ttl_hours: int = 24
) -> None:
    """Cache GitHub metrics for a repo (default 24 hours)."""
    _set(f"gh-metrics:{repo}", {"metrics": metrics, "derived": derived or {}}, ttl_hours * 3600)
    logger.info(f"Cached GitHub metrics for {repo}")


# =============================================================================
# GitHub list-data cache (issues / discussions)
# =============================================================================

def get_cached_github_data(repo: str, data_type: str) -> Optional[list]:
    """Return cached GitHub list data ('issues' or 'discussions'), or None."""
    entry = _get(f"gh-data:{repo}:{data_type}")
    if entry is not None:
        logger.info(f"GitHub {data_type} cache HIT for {repo}")
        return entry["data"]
    logger.info(f"GitHub {data_type} cache MISS for {repo}")
    return None


def store_github_data_cache(
    repo: str, data_type: str, data: list, ttl_hours: int = 24
) -> None:
    """Cache GitHub list data ('issues' or 'discussions') for a repo (default 24 hours)."""
    _set(f"gh-data:{repo}:{data_type}", {"data": data}, ttl_hours * 3600)
    logger.info(f"Cached {len(data)} {data_type} for {repo}")
