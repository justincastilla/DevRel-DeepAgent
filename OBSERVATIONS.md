# Codebase Observations & Recommendations

_Author: automated code review • Date: 2026-07-01_

This document captures an analysis of the **DevRel Research Agent** codebase and a
concrete, step-by-step plan for the two goals you asked for:

1. **Replace the Elasticsearch-based caching with Redis** (the headline task).
2. **General recommendations** to make this a clearer teaching tool for
   DeepAgents + Elasticsearch + Tavily.

Guiding principle throughout: **prefer simpler, easy-to-read code**. Several of the
suggestions below _remove_ code rather than add it — Redis's native key-expiry lets
us delete an entire cleanup subsystem.

> **Status (2026-07-01):** ✅ **Part 2 (Redis migration) has been implemented** — all
> 14 steps are done and verified (round-trip, TTL expiry, and graceful-degradation
> tests pass). Part 3 (general code) and Part 4 (docs) remain as open recommendations,
> except for the caching-related doc updates which were completed as part of Part 2.

---

## Part 1 — Big Picture

The project is well-organized and genuinely useful as a teaching artifact. Strengths
worth keeping:

- Clean separation of tools by domain (`tools/github_tools.py`, `tools/web_tools.py`,
  `tools/elasticsearch_tools.py`, `tools/scoring_tools.py`).
- Lazy, thread-safe agent initialization in [agent.py](agent.py).
- Config secrets are masked before logging ([config.py](config.py)).
- The **caching layer is already cleanly isolated** behind six functions, which makes
  the Redis swap low-risk (see Part 2).

The main friction for a _learner_ is that a few concepts are spread thin and the caching
story requires reading three different indices + a cleanup job + a scheduled workflow to
understand. **Moving to Redis is not just a backend swap — it is a genuine simplification
of the mental model**, which is exactly what an educational repo wants.

---

## Part 2 — Replace Elasticsearch Caching with Redis

### 2.1 What is actually a "cache" today

Only **three** of the many Elasticsearch indices are true ephemeral caches. Everything
else is a permanent data store and should **stay in Elasticsearch**.

| Index | Purpose | Read/Write functions (in `tools/elasticsearch_tools.py`) | Move to Redis? |
|-------|---------|-----------------------------------------------------------|----------------|
| `web-search-cache` | Cached Tavily results (7-day TTL) | `get_cached_search` / `store_search_cache` | ✅ **Yes** |
| `github-metrics-cache` | Cached repo metrics (24-hour TTL) | `get_cached_github_metrics` / `store_github_metrics_cache` | ✅ **Yes** |
| `github-data-cache` | Cached issues/discussions (24-hour TTL) | `get_cached_github_data` / `store_github_data_cache` | ✅ **Yes** |
| `research-reports` | Persistent reports; `get_cached_report` reads recent ones | `get_cached_report` / `get_latest_report` / `store_research_report` | ❌ **No — keep in ES** |
| `technology-research`, `repo-timeseries`, `commit-history`, `adoption-signals`, `technology-discoveries` | Historical/analytical data | — | ❌ **No — keep in ES** |

> **Important scoping note:** `get_cached_report()` is _named_ like a cache but it reads
> from the permanent `research-reports` index (used for trend analysis and the Elastic
> Agent Builder tools). Leave it in Elasticsearch. Only the three ephemeral caches move.

### 2.2 Why Redis makes the code simpler

The current ES cache pattern requires, for every cache type:
- a hand-written `bool`/`range`/`term` query,
- a `sort` + `size: 1` to get the freshest doc,
- a manual timestamp cutoff (`datetime.utcnow() - timedelta(...)`),
- **and** a separate cleanup pass (`cleanup_all_caches`, `cleanup_cache_index`,
  `_CACHE_TTL_HOURS`) plus a scheduled Elastic workflow
  ([workflows/01_cache_cleanup.yaml](workflows/01_cache_cleanup.yaml)) to stop the
  indices growing forever.

Redis replaces **all of that** with `SET key value EX ttl` + `GET key`. Expiry is
automatic, so the entire cleanup subsystem is deleted. This is the single biggest
readability win in the project.

### 2.3 Target design — one tiny module

Create **`tools/cache.py`** as the whole caching layer. Everything funnels through two
helpers so the specific functions become 2–3 lines each:

```python
"""Redis-backed cache for external API results.

Redis handles expiry natively via per-key TTL, so there is no cleanup job:
stale keys simply disappear. If Redis is unavailable, every function degrades
to a cache MISS and the app keeps working.
"""

import hashlib
import json
from typing import Optional

import redis

from config import config
from utils.logging_utils import get_logger

logger = get_logger(__name__)

# Lazy singleton client. decode_responses=True so we get str back, not bytes.
_client: Optional[redis.Redis] = None


def _redis() -> Optional[redis.Redis]:
    global _client
    if _client is None and config.REDIS_URL:
        _client = redis.from_url(config.REDIS_URL, decode_responses=True)
    return _client


def _get(key: str) -> Optional[dict]:
    """Return the cached JSON value for key, or None on miss/error."""
    client = _redis()
    if not client:
        return None
    try:
        raw = client.get(key)
        return json.loads(raw) if raw else None
    except Exception as e:  # never let a cache problem break the request
        logger.warning(f"Cache read failed for {key} (continuing): {e}")
        return None


def _set(key: str, value: dict, ttl_seconds: int) -> None:
    """Store value as JSON under key with a TTL. Redis expires it for us."""
    client = _redis()
    if not client:
        return
    try:
        client.set(key, json.dumps(value), ex=ttl_seconds)
    except Exception as e:
        logger.warning(f"Cache write failed for {key} (continuing): {e}")


def _hash_query(query: str) -> str:
    return hashlib.sha256(query.lower().strip().encode()).hexdigest()[:16]


# --- Web search cache -------------------------------------------------------

def get_cached_search(query: str) -> Optional[dict]:
    return _get(f"search:{_hash_query(query)}")


def store_search_cache(query: str, results: dict, ttl_days: int = 7) -> None:
    _set(f"search:{_hash_query(query)}", results, ttl_days * 86400)


# --- GitHub metrics cache ---------------------------------------------------

def get_cached_github_metrics(repo: str) -> Optional[dict]:
    return _get(f"gh-metrics:{repo}")


def store_github_metrics_cache(repo, metrics, derived=None, ttl_hours: int = 24) -> None:
    _set(f"gh-metrics:{repo}", {"metrics": metrics, "derived": derived or {}}, ttl_hours * 3600)


# --- GitHub list-data cache (issues / discussions) --------------------------

def get_cached_github_data(repo: str, data_type: str) -> Optional[list]:
    entry = _get(f"gh-data:{repo}:{data_type}")
    return entry["data"] if entry else None


def store_github_data_cache(repo, data_type, data, ttl_hours: int = 24) -> None:
    _set(f"gh-data:{repo}:{data_type}", {"data": data}, ttl_hours * 3600)
```

That's the entire caching layer — roughly 70 lines replacing ~250 lines of ES query
code plus the cleanup subsystem.

### 2.4 Behavioral change to call out (and it's fine for teaching)

With ES, the **max age was decided at read time** (`max_age_days` / `max_age_hours`
params). With Redis, the **TTL is decided at write time** (`ex=`). This means the
per-call `cache_days` / `cache_hours` knobs now set the write TTL instead of a read
filter. For this tool that's simpler and perfectly acceptable — just keep the tool
signatures and pass the value through as the TTL. Note it in the walkthrough so learners
understand the difference between "query-time freshness" and "write-time expiry".

The one piece of real logic to **preserve**: `get_cached_github_metrics` currently
recomputes `issue_close_rate` / `pr_merge_rate` on read when they're missing
([elasticsearch_tools.py:602-614](tools/elasticsearch_tools.py)). Keep that recompute —
move it into `fetch_repo_metrics` in `github_tools.py` (where the cache result is
consumed) so `tools/cache.py` stays a dumb key/value store.

### 2.5 Step-by-step TODO — Redis migration

- [ ] **1. Add the dependency.** Add `redis>=5.0.0` to [requirements.txt](requirements.txt).
- [ ] **2. Add config.** In [config.py](config.py) add
      `REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")`. Do **not** add it
      to `validate()` required-vars — the cache must be optional (app runs without it).
- [ ] **3. Create `tools/cache.py`** using the design in §2.3.
- [ ] **4. Rewire `web_tools.py`.** Change the import from
      `tools.elasticsearch_tools` to `tools.cache` for `get_cached_search` /
      `store_search_cache`. Update the call in `tavily_search` — `get_cached_search(query)`
      no longer takes `max_age_days`; pass `cache_days` to `store_search_cache` instead.
- [ ] **5. Rewire `github_tools.py`.** Switch the four cache imports to `tools.cache`.
      In `fetch_repo_metrics`, move the `issue_close_rate` / `pr_merge_rate` recompute
      (from §2.4) to run on the cached result. Update `get_cached_github_data` /
      `get_cached_github_metrics` call sites to drop the `max_age_*` args.
- [ ] **6. Delete the ES cache functions** from
      [tools/elasticsearch_tools.py](tools/elasticsearch_tools.py):
      `_hash_query`, `get_cached_search`, `store_search_cache`,
      `get_cached_github_metrics`, `store_github_metrics_cache`,
      `get_cached_github_data`, `store_github_data_cache`, and the whole
      **Cache Cleanup** block (`_CACHE_TTL_HOURS`, `cleanup_cache_index`,
      `cleanup_all_caches`). Keep `get_cached_report` — it belongs to `research-reports`.
- [ ] **7. Update `tools/__init__.py`.** Import the six cache functions from
      `.cache` instead of `.elasticsearch_tools`; remove `cleanup_all_caches` /
      `cleanup_cache_index` from imports and `__all__`.
- [ ] **8. Remove the startup cleanup** in [web_app.py](web_app.py): delete the
      `cleanup_all_caches` import and the call inside `lifespan()`. Redis TTL makes it
      unnecessary. (The `lifespan` handler can be removed entirely if nothing else uses it.)
- [ ] **9. Delete [workflows/01_cache_cleanup.yaml](workflows/01_cache_cleanup.yaml).**
      Redis expiry replaces the scheduled delete-by-query job. Add a one-line note to the
      `workflows/` folder (or the walkthrough) explaining why it's gone.
- [ ] **10. Trim `scripts/setup_elasticsearch.py`.** Remove the `web-search-cache`,
      `github-metrics-cache`, and `github-data-cache` index mappings — they're no longer
      created. Leave the analytical indices intact.
- [ ] **11. Update infra.** Add a `redis` service to
      [docker-compose.yml](docker-compose.yml) and set `REDIS_URL=redis://redis:6379/0`
      in the web service env:
      ```yaml
        redis:
          image: redis:7-alpine
          ports: ["6379:6379"]
      ```
      Add `REDIS_URL` to [example.env](example.env).
- [ ] **12. Update the docs** (README, walkthrough, CLAUDE.md, elastic_agent_tools.md):
      remove the three cache indices from index tables, describe the Redis cache + native
      TTL, and note that cache cleanup no longer exists. Update the "Data Storage" section
      of [CLAUDE.md](CLAUDE.md).
- [ ] **13. Add a tiny test** `scripts/test_cache.py`: set → get → miss-after-expiry
      (use a 1s TTL), and confirm graceful degradation when `REDIS_URL` is unset.
- [ ] **14. Manual verify:** run an evaluation twice; second run should log cache HITs
      for metrics/search and be noticeably faster.

---

## Part 3 — General Code Recommendations

Ordered roughly by value-to-a-learner. None are blocking; each favors clarity.

### 3.1 Config indirection is confusing (quick win)
[config.py](config.py) maps env names to differently-named attributes:
`ELASTICSEARCH_URL = os.getenv("ELASTICSEARCH_HOST")` and
`GITHUB_TOKEN = os.getenv("GITHUB_API_KEY")`. CLAUDE.md documents the env var as
`GITHUB_TOKEN`, but the code reads `GITHUB_API_KEY`. Pick one name per concept and use it
everywhere (env, config attr, docs). This trips up every newcomer.
- [ ] Align env-var names between `.env`, `config.py`, and the docs.

### 3.2 `example.env` is out of sync
It lists `ELASTICSEARCH_AGENT_HOST` (never read by `config.py`) and omits many real vars
(`ANTHROPIC_FOUNDRY_RESOURCE`, `AZURE_OPENAI_*`, `ELASTIC_AGENT_ID`, `KIBANA_*`,
`LANGCHAIN_PROJECT`, `RECURSION_LIMIT`, `LOG_LEVEL`). A learner copying it gets a broken
config.
- [ ] Regenerate `example.env` from the actual keys `config.py` reads (plus `REDIS_URL`).
      Group by required vs optional with comments.

### 3.3 The ES "sanitizer" functions are heavy defensive code
`sanitize_metrics_for_es` / `sanitize_analysis_for_es`
([elasticsearch_tools.py:85-176](tools/elasticsearch_tools.py)) are ~90 lines of type
coercion. Now that `store_research_snapshot` accepts typed **Pydantic** models
(`SnapshotMetrics`, `SnapshotAnalysis`), most of this coercion is redundant. Simplifying
here would materially improve readability.
- [ ] After confirming the Pydantic models are always used, reduce the sanitizers to the
      minimum still needed (or drop them). Add a short comment explaining what remains and why.

### 3.4 `datetime.utcnow()` is deprecated (Python 3.12)
Used throughout `elasticsearch_tools.py`. The Dockerfile is `python:3.12-slim`, where this
emits `DeprecationWarning`.
- [ ] Replace with `datetime.now(timezone.utc)` (and drop the trailing `.isoformat()`
      tz caveats). Low effort, removes warning noise learners will see.

### 3.5 `cli.py` is a 49 KB monolith
It's by far the largest module and mixes argument parsing, formatting, ES access, and
report I/O. Not urgent, but for a teaching repo consider splitting display/formatting
helpers into `cli_display.py`.
- [ ] (Optional) Extract formatting/report-rendering helpers out of `cli.py`.

### 3.6 Redundant local `import json`
`get_cached_github_data` / `store_github_data_cache` re-`import json` inside the function
though it's already imported at module top. This goes away when those functions move to
`tools/cache.py`, but worth noting as a pattern to avoid.

### 3.7 Over-broad secret-scrubbing regex
`_API_KEY_PATTERNS` in [config.py](config.py) includes
`[a-zA-Z0-9+/]{40,}={0,2}`, which matches any 40+ char alphanumeric run and can mangle
innocent log text (hashes, IDs, base64 payloads).
- [ ] (Optional) Tighten or remove the generic base64 pattern; keep the vendor-prefixed
      ones (`sk-`, `ghp_`, `tvly-`, …) which are precise.

### 3.8 Model IDs
[agent.py](agent.py) pins `anthropic:claude-sonnet-4-5-20250929` and `azure:gpt-5.4`.
For a demo that stays relevant, consider centralizing model IDs in `config.py` so there's
one place to update, and note in docs that these are swappable.
- [ ] (Optional) Move `MODELS` map / defaults into config and document how to change them.

---

## Part 4 — Documentation Observations

The docs are well-intentioned but fragmented; for an educational repo, tightening them
matters as much as the code.

- [ ] **QUICKSTART.md is a trap.** It omits the required Kibana step (creating the ES|QL
      tools from `elastic_agent_tools.md`). Following it alone yields a working CLI but a
      silently-failing `elastic-agent`. Add the Kibana setup step, or clearly mark the
      Elastic Agent Builder pieces as optional.
- [ ] **`python agent.py "query"` in QUICKSTART** — verify this path; the CLI
      (`python cli.py ...`) should be the primary documented entry point.
- [ ] **Caching is documented in 3 places** with different depth (README lists indices,
      walkthrough explains hit/miss, elastic_agent_tools shows ES|QL). After the Redis
      migration, consolidate into **one** short "How Caching Works" section and delete the
      ES cache-index references.
- [ ] **Consistency fixes:** README says 8 phases, PROJECT_SUMMARY says 7; tool counts
      vary ("9 core", "16 elastic"); README "Planned Features" lists the web UI that
      already exists. Reconcile these.
- [ ] **`github-data-cache`** is listed in index tables but never explained in the caching
      narrative — moot after migration, but fix any lingering references.
- [ ] **PROJECT_SUMMARY.md** is an outdated internal checklist (no web UI, no caching).
      Either refresh it or fold it into README to reduce drift.

---

## Suggested order of execution

1. **Redis migration** (Part 2) — highest value, and it deletes code.
2. **Config + example.env cleanup** (3.1, 3.2) — unblocks new users immediately.
3. **Doc consolidation** (Part 4) — especially the caching section and QUICKSTART fix.
4. **Optional polish** (3.3–3.8) as time allows.
