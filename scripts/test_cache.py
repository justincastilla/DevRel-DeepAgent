"""
Test script for the Redis cache layer (tools/cache.py).

Verifies:
  1. store -> get round-trips a value
  2. a short TTL expires the key (Redis handles expiry, no cleanup job)
  3. the app degrades gracefully to a MISS when Redis is unreachable

Requires a running Redis (see docker-compose.yml, or `docker run -p 6379:6379 redis`).
If Redis is not reachable, the test reports that instead of failing hard.
"""

import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import cache


def redis_available() -> bool:
    client = cache._redis()
    if not client:
        return False
    try:
        client.ping()
        return True
    except Exception:
        return False


def test_roundtrip_and_expiry():
    query = "pytest-cache-roundtrip-probe"
    payload = {"results": [{"title": "hello"}], "answer": "world"}

    # Store with a 1-second TTL so we can watch Redis expire it on its own.
    cache._set(f"search:{cache._hash_query(query)}", payload, ttl_seconds=1)

    hit = cache.get_cached_search(query)
    assert hit == payload, f"expected round-trip payload, got {hit!r}"
    print("PASS: store -> get round-trips the cached value")

    time.sleep(1.2)
    miss = cache.get_cached_search(query)
    assert miss is None, f"expected key to expire, still got {miss!r}"
    print("PASS: key expired automatically after its TTL (no cleanup job needed)")


def test_graceful_degradation():
    # Point the client at a dead port and confirm we get a MISS, not a crash.
    saved_client = cache._client
    import redis
    cache._client = redis.from_url("redis://127.0.0.1:6390/0", decode_responses=True)
    try:
        assert cache.get_cached_search("anything") is None
        cache.store_search_cache("anything", {"results": []})  # must not raise
        print("PASS: unreachable Redis degrades to a cache MISS without raising")
    finally:
        cache._client = saved_client


if __name__ == "__main__":
    print("=" * 60)
    print("Redis cache layer test")
    print("=" * 60)

    if not redis_available():
        print("SKIP: Redis is not reachable at REDIS_URL.")
        print("      Start one with: docker run --rm -p 6379:6379 redis:7-alpine")
        sys.exit(0)

    test_roundtrip_and_expiry()
    test_graceful_degradation()
    print("\nAll cache tests passed.")
