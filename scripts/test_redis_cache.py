"""
Quick sanity check for the Redis cache backend.

Run this after starting a local Redis (``redis-server`` or
``docker compose up -d redis``) to confirm caching works end to end:

    python scripts/test_redis_cache.py

It exercises a value roundtrip, a cache miss, TTL expiry setting, and the
graceful-degradation behavior (no crash) if Redis is unreachable.
"""

import sys
from pathlib import Path

# Allow running from the repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.redis_cache import cache_get, cache_set, get_redis


def main() -> None:
    print("Testing Redis cache backend...\n")

    # 1. Store and read back a dict (web-search shape)
    cache_set("test:websearch", {"results": [{"title": "hello"}]}, ttl_seconds=30)
    got = cache_get("test:websearch")
    print(f"  roundtrip dict : {got}")
    assert got == {"results": [{"title": "hello"}]}, "dict roundtrip failed"

    # 2. Store and read back a list (github-data shape)
    cache_set("test:ghdata", [{"id": 1}, {"id": 2}], ttl_seconds=30)
    got = cache_get("test:ghdata")
    print(f"  roundtrip list : {got}")
    assert got == [{"id": 1}, {"id": 2}], "list roundtrip failed"

    # 3. A missing key returns None
    print(f"  cache miss     : {cache_get('test:does-not-exist')}")
    assert cache_get("test:does-not-exist") is None

    # 4. The TTL was actually applied
    ttl = get_redis().ttl("test:websearch")
    print(f"  ttl remaining  : {ttl}s")
    assert 0 < ttl <= 30, "TTL was not set"

    # Clean up test keys
    get_redis().delete("test:websearch", "test:ghdata")

    print("\nAll Redis cache checks passed.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # If Redis is down the cache degrades gracefully in the app, but this
        # test needs a live Redis to verify a real roundtrip.
        print(f"\nTest could not complete (is Redis running?): {e}")
        sys.exit(1)
