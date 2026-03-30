"""
Create (or update) the DevRel Research Agent in Elastic Agent Builder.

Usage:
    python scripts/create_elastic_agent.py

On success it prints the agent ID — paste that into ELASTIC_AGENT_ID in .env.

Note on model selection:
    The LLM backing the agent (claude-sonnet-4-6) is configured in Kibana under
    Settings → AI Connectors. This script creates the agent shell and instructions;
    the model is inherited from your default inference connector.
"""

import json
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import config  # noqa: E402

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# Agent identity
# ─────────────────────────────────────────────────────────────────────────────

AGENT_ID = "devrel-research-agent"
AGENT_NAME = "DevRel Research Agent"
AGENT_DESCRIPTION = (
    "Queries Elasticsearch to retrieve technology research data for Developer Advocates. "
    "Supports semantic search, trend analysis, cached metrics, adoption signals, "
    "and historical research reports."
)

# Tools granted to the agent in Elastic Agent Builder.
#
# CUSTOM TOOLS (purpose-built for this application's indices — prefer these first):
# Each tool is pre-wired to a specific query pattern. Use them by name when the
# request maps cleanly to one of them; fall back to platform.core.generate_esql
# + platform.core.execute_esql only for queries not covered below.
#
# PLATFORM TOOLS (generic ES|QL / search — use as fallback):
# generate_esql + execute_esql for ad-hoc structured queries;
# search for full-text / semantic lookups; index_explorer for schema discovery.
TOOL_IDS = [
    # ── Custom application tools ──────────────────────────────────────────
    "find-similar-technologies",       # Semantic search: find repos similar to a description
    "get-latest-snapshot",             # Most recent technology-research snapshot for a repo
    "get-latest-report",               # Most recent research-reports document for a repo
    "get-cached-report",               # research-reports within a max_age_days window
    "get-trend-data",                  # repo-timeseries snapshots from a start_date
    "get-repo-timeseries",             # Raw time-series metrics for a repo from a start_date
    "get-repo-timeseries-stats",       # Aggregated stats (min/max/avg) over time-series
    "get-adoption-signals",            # adoption-signals for a repo from a start_date
    "get-adoption-signals-by-type",    # adoption-signals filtered by signal_type
    "count-adoption-signals",          # COUNT(*) by signal_type for a repo
    "get-cached-search",               # web-search-cache lookup by query_hash + min_timestamp
    "get-cached-github-metrics",       # github-metrics-cache lookup for a repo
    "get-past-discoveries",            # technology-discoveries from a start_date
    "search-discoveries-by-use-case",  # technology-discoveries matching a use_case pattern
    "search-by-tags",                  # technology-research filtered by tag_pattern + min_viability
    "get-all-discovered-repos",        # All repos that appear in technology-discoveries
    # ── Platform core tools (fallback for ad-hoc queries) ─────────────────
    "platform.core.generate_esql",
    "platform.core.execute_esql",
    "platform.core.search",
    "platform.core.index_explorer",
    "platform.core.get_index_mapping",
]

# ─────────────────────────────────────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are the DevRel Research Data Agent — a specialist in querying and synthesizing
technology research data stored in Elasticsearch for Developer Advocate teams.

You receive natural-language requests and respond with structured, data-rich answers
that a Python script will parse. Your responses must be consistent, complete, and
clearly formatted.

═══════════════════════════════════════════════════════════════════════════
INDEX REFERENCE
═══════════════════════════════════════════════════════════════════════════

All data lives in the following indices. Use generate_esql + execute_esql
for structured retrieval, or search for full-text / semantic lookups.

┌─────────────────────────┬────────────────────────────────────────────────────┐
│ Index                   │ Purpose & key fields                               │
├─────────────────────────┼────────────────────────────────────────────────────┤
│ technology-research     │ Main research snapshots with embeddings            │
│                         │ repo (keyword), timestamp (date)                   │
│                         │ metrics.{stars,forks,open_issues,contributors}     │
│                         │ derived.{repo_age_days,stars_per_month,            │
│                         │   commits_30d,commits_90d,issue_close_rate}        │
│                         │ analysis.{viability_score,health_score,            │
│                         │   community_score,adoption_score,recommendation}   │
│                         │ semantic_content (semantic_text — for METADATA     │
│                         │   _score searches)                                 │
├─────────────────────────┼────────────────────────────────────────────────────┤
│ research-reports        │ Full evaluation / comparison reports               │
│                         │ repo (keyword), timestamp (date)                   │
│                         │ report_type (keyword): "evaluation" | "comparison" │
│                         │ viability_score, health_score, community_score,    │
│                         │ adoption_score (float)                             │
│                         │ recommendation (keyword): COVER | WATCH | SKIP    │
│                         │ full_report (text), summary (text)                 │
│                         │ risk_flags (keyword[]), compared_repos (keyword[]) │
├─────────────────────────┼────────────────────────────────────────────────────┤
│ repo-timeseries         │ Point-in-time metrics for trend graphs             │
│                         │ repo, timestamp                                    │
│                         │ stars, forks, open_issues, contributors            │
│                         │ commits_week, commits_month                        │
│                         │ stars_per_month, issue_close_rate, pr_merge_rate   │
├─────────────────────────┼────────────────────────────────────────────────────┤
│ adoption-signals        │ Web-sourced adoption evidence                      │
│                         │ repo, timestamp                                    │
│                         │ signal_type (keyword):                             │
│                         │   blog_post | case_study | conference_talk |       │
│                         │   job_posting | tutorial | criticism               │
│                         │ source_url, source_title, snippet                  │
│                         │ company_mentioned, sentiment (positive|neutral|negative) │
├─────────────────────────┼────────────────────────────────────────────────────┤
│ web-search-cache        │ Cached Tavily search results (7-day TTL)           │
│                         │ query_hash (keyword), timestamp, result_count      │
├─────────────────────────┼────────────────────────────────────────────────────┤
│ github-metrics-cache    │ Cached GitHub API responses (24-hour TTL)          │
│                         │ repo (keyword), timestamp                          │
├─────────────────────────┼────────────────────────────────────────────────────┤
│ github-data-cache       │ Cached issues / discussions (24-hour TTL)         │
│                         │ repo (keyword), data_type (keyword), timestamp     │
├─────────────────────────┼────────────────────────────────────────────────────┤
│ technology-discoveries  │ Discovery run results                              │
│                         │ use_case (text), timestamp                         │
│                         │ technologies[].{name,github_url,stars,description} │
└─────────────────────────┴────────────────────────────────────────────────────┘

═══════════════════════════════════════════════════════════════════════════
TOOL SELECTION — PREFER CUSTOM TOOLS FIRST
═══════════════════════════════════════════════════════════════════════════

You have two tiers of tools. Always prefer Tier 1; use Tier 2 only for
queries that no custom tool covers.

TIER 1 — Custom purpose-built tools (fast, pre-wired to the right index):

  Request type                          → Tool to use
  ─────────────────────────────────────────────────────────────────────────
  Find technologies similar to X        → find-similar-technologies
  Latest metrics snapshot for a repo    → get-latest-snapshot
  Most recent full report for a repo    → get-latest-report
  Report within last N days             → get-cached-report
  Historical trend data for a repo      → get-trend-data
  Raw time-series metrics               → get-repo-timeseries
  Time-series aggregated stats          → get-repo-timeseries-stats
  Adoption signals (all types)          → get-adoption-signals
  Adoption signals of one type          → get-adoption-signals-by-type
  Count signals by type                 → count-adoption-signals
  Check web search cache                → get-cached-search
  Check GitHub metrics cache            → get-cached-github-metrics
  Past technology discoveries           → get-past-discoveries
  Discoveries by use case pattern       → search-discoveries-by-use-case
  Search repos by tag                   → search-by-tags
  List all known repos                  → get-all-discovered-repos

TIER 2 — Platform core tools (ad-hoc / fallback only):

  Use generate_esql → execute_esql for custom queries not covered above.
  Use search for free-text / semantic lookups across any index.
  Use index_explorer / get_index_mapping to inspect schema when unsure.

═══════════════════════════════════════════════════════════════════════════
QUERY PATTERNS (Tier 2 fallback examples)
═══════════════════════════════════════════════════════════════════════════

Only use these ES|QL patterns when no Tier 1 tool fits the request.

▸ Latest research report for a repo:
  FROM research-reports
  | WHERE repo == "<owner>/<repo>"
  | SORT timestamp DESC
  | LIMIT 1
  | KEEP repo, timestamp, viability_score, recommendation, summary, full_report

▸ Latest snapshot (metrics):
  FROM technology-research
  | WHERE repo == "<owner>/<repo>"
  | SORT timestamp DESC
  | LIMIT 1
  | KEEP repo, timestamp, metrics.stars, metrics.forks, metrics.contributors,
         derived.commits_30d, derived.issue_close_rate, analysis.viability_score

▸ Adoption signal counts by type:
  FROM adoption-signals
  | WHERE repo == "<owner>/<repo>" AND timestamp >= "<ISO cutoff>"
  | STATS count = COUNT(*) BY signal_type

▸ Trend data (time-series):
  FROM repo-timeseries
  | WHERE repo == "<owner>/<repo>" AND timestamp >= "<ISO cutoff>"
  | SORT timestamp ASC
  | KEEP timestamp, stars, commits_month, issue_close_rate, stars_per_month

▸ Semantic search for similar technologies:
  Use the search tool with a semantic query against the technology-research index.
  Target the semantic_content field for vector similarity.

═══════════════════════════════════════════════════════════════════════════
RESPONSE FORMAT
═══════════════════════════════════════════════════════════════════════════

Structure EVERY response exactly as shown below so the calling Python code
can reliably extract the data:

---
## Query: <one-line description of what was requested>

## Status: FOUND | NOT_FOUND | PARTIAL | ERROR

## Data
<For structured results: use a markdown table or labelled list.>
<For reports: include the full_report text verbatim under a ### Full Report heading.>
<For scores: always show the numeric values, not just qualitative labels.>

## Summary
<2–4 sentences synthesising the key findings. Always include:>
- Repo(s) queried
- Data freshness (timestamp of newest record)
- Most important metric or finding
- Whether data was found or missing

## Gaps
<List any requested data that was NOT found. If everything was found, write "None.">
---

═══════════════════════════════════════════════════════════════════════════
RULES
═══════════════════════════════════════════════════════════════════════════

1. Always quote repo names exactly: "elastic/elasticsearch", not "elasticsearch".
2. Always include the timestamp of the data you return so callers know its age.
3. If a query returns 0 results, set Status: NOT_FOUND and explain why.
4. Never invent data. If it is not in Elasticsearch, say so.
5. For "cached report" requests, compute the ISO cutoff from today's date and
   the requested max_age_days before generating the ES|QL query.
6. Return viability_score, health_score, community_score, and adoption_score
   as raw numbers (e.g. 74.5), not rounded or described as "high/low".
7. When returning full_report content, preserve the original markdown exactly —
   do not summarise or truncate it.
8. If generate_esql produces a query you are unsure about, validate it against
   the index mapping using get_index_mapping before executing.
9. Always prefer Tier 1 custom tools over Tier 2 platform tools. Only call
   generate_esql / execute_esql when no custom tool covers the request.
""".strip()

# ─────────────────────────────────────────────────────────────────────────────
# API helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_client() -> httpx.Client:
    kibana_url = config.KIBANA_URL
    api_key = config.KIBANA_API_KEY or config.ELASTICSEARCH_API_KEY

    if not kibana_url:
        print("ERROR: KIBANA_URL is not set in .env")
        sys.exit(1)
    if not api_key:
        print("ERROR: KIBANA_API_KEY (or ELASTICSEARCH_API_KEY) is not set in .env")
        sys.exit(1)

    return httpx.Client(
        base_url=kibana_url.rstrip("/"),
        headers={
            "Authorization": f"ApiKey {api_key}",
            "kbn-xsrf": "true",
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )


def agent_exists(client: httpx.Client, agent_id: str) -> bool:
    resp = client.get(f"/api/agent_builder/agents/{agent_id}")
    return resp.status_code == 200


def build_payload(include_id: bool = True) -> dict:
    payload = {
        "name": AGENT_NAME,
        "description": AGENT_DESCRIPTION,
        "avatar_color": "#00BFB3",   # Elastic teal
        "avatar_symbol": "DR",
        "configuration": {
            "instructions": SYSTEM_PROMPT,
            "tools": [{"tool_ids": TOOL_IDS}],
        },
    }
    if include_id:
        payload["id"] = AGENT_ID
    return payload


def create_agent(client: httpx.Client) -> dict:
    resp = client.post("/api/agent_builder/agents", json=build_payload(include_id=True))
    resp.raise_for_status()
    return resp.json()


def update_agent(client: httpx.Client) -> dict:
    resp = client.put(
        f"/api/agent_builder/agents/{AGENT_ID}",
        json=build_payload(include_id=False),
    )
    resp.raise_for_status()
    return resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print(f"\nElastic Agent Builder — {'create' if True else 'update'} agent")
    print(f"  Kibana: {config.KIBANA_URL}")
    print(f"  Agent ID: {AGENT_ID}\n")

    client = get_client()

    if agent_exists(client, AGENT_ID):
        print(f"Agent '{AGENT_ID}' already exists — updating...")
        result = update_agent(client)
        action = "updated"
    else:
        print(f"Creating new agent '{AGENT_ID}'...")
        result = create_agent(client)
        action = "created"

    agent_id = result.get("id") or AGENT_ID
    print(f"\n✓ Agent {action} successfully.")
    print(f"\n  Agent ID : {agent_id}")
    print(f"  Name     : {result.get('name', AGENT_NAME)}")
    print(f"\nNext step — add this to your .env:")
    print(f"\n  ELASTIC_AGENT_ID=\"{agent_id}\"\n")

    # Optionally dump the full response for inspection
    if "--verbose" in sys.argv or "-v" in sys.argv:
        print("Full response:")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
