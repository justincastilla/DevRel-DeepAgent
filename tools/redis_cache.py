"""
Redis-backed cache for the DevRel Research Agent.

This module replaces the Elasticsearch-based caching that used to live inside
tools/elasticsearch_tools.py. Redis is a natural fit for a cache because:

  * it expires keys for us via native TTL, so there is no cleanup job to run, and
  * a cache lookup is a single O(1) GET instead of a search query.

Only the three throwaway caches moved here (web-search results, GitHub metrics,
and GitHub issue/discussion lists). Durable, queryable data - research
snapshots, time-series, reports, adoption signals, discoveries - still lives in
Elasticsearch because it needs semantic search, aggregations, and history.

Every value is stored as a JSON string. If Redis is unreachable the helpers
degrade gracefully: reads return None (treated as a cache miss) and writes are
silently skipped, so the agent keeps working without a cache.
"""

import json
from typing import Optional

import redis

from config import config
from utils.logging_utils import get_logger

logger = get_logger(__name__)

# Module-level singleton so the whole process shares one connection pool
# instead of opening a new connection on every cache call.
_redis_client: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    """Return a shared Redis client, creating it on first use."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            db=config.REDIS_DB,
            password=config.REDIS_PASSWORD or None,
            decode_responses=True,  # work with str, not bytes
        )
    return _redis_client


def cache_get(key: str):
    """
    Look up a key in Redis.

    Returns the decoded JSON value (a dict or list), or None on a cache miss
    or any connection error.
    """
    try:
        raw = get_redis().get(key)
    except Exception as e:
        logger.warning(f"Redis GET failed for '{key}' (continuing without cache): {e}")
        return None

    if raw is None:
        return None

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(f"Cached value for '{key}' was not valid JSON; ignoring")
        return None


def cache_set(key: str, value, ttl_seconds: int) -> None:
    """
    Store a JSON-serializable value under a key with a TTL (in seconds).

    Redis deletes the key automatically once the TTL elapses, so there is no
    separate cleanup step. Failures are logged and ignored.
    """
    try:
        get_redis().set(key, json.dumps(value), ex=ttl_seconds)
    except Exception as e:
        logger.warning(f"Redis SET failed for '{key}' (continuing without cache): {e}")
