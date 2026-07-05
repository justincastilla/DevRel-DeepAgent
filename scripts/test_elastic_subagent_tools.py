"""
Smoke-test the elastic-agent subagent's direct-Elasticsearch tools.

Calls each read-only tool against the live Elasticsearch cluster and prints a
one-line summary. Empty results are expected on a fresh cluster and count as a
PASS (the tool ran and returned structured data without error).

Usage:
    python scripts/test_elastic_subagent_tools.py
    python scripts/test_elastic_subagent_tools.py --repo elastic/elasticsearch
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from subagents.elastic_agent import ELASTIC_SUBAGENT_TOOLS  # noqa: E402


def summarize(result) -> str:
    if isinstance(result, list):
        return f"list ({len(result)} records)"
    if isinstance(result, dict):
        if result.get("found") is False:
            return "dict (not found)"
        return f"dict ({len(result)} keys)"
    return f"{type(result).__name__}: {str(result)[:60]}"


# Minimal valid args per tool name.
def args_for(tool_name: str, repo: str) -> dict:
    if tool_name == "find_similar_technologies":
        return {"description": "AI agent orchestration frameworks", "limit": 3}
    if tool_name in ("get_trend_data", "search_repo_timeseries"):
        return {"repo_name": repo} if tool_name == "get_trend_data" else {"repo": repo}
    if tool_name == "search_by_tags":
        return {"tags": ["ai-agents"], "min_viability": 0}
    if tool_name == "compare_technologies":
        return {"repos": [repo]}
    if tool_name == "search_adoption_signals":
        return {"repo": repo}
    if tool_name in ("fetch_latest_report", "fetch_cached_report"):
        return {"repo": repo}
    if tool_name == "search_past_discoveries":
        return {}
    if tool_name == "list_discovered_repos":
        return {}
    return {}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="elastic/elasticsearch")
    args = parser.parse_args()

    print(f"\nTesting {len(ELASTIC_SUBAGENT_TOOLS)} elastic-agent tools "
          f"(repo={args.repo})\n")

    failures = 0
    for tool in ELASTIC_SUBAGENT_TOOLS:
        try:
            result = tool.invoke(args_for(tool.name, args.repo))
            print(f"  [PASS] {tool.name}: {summarize(result)}")
        except Exception as e:
            failures += 1
            print(f"  [FAIL] {tool.name}: {type(e).__name__}: {str(e)[:80]}")

    total = len(ELASTIC_SUBAGENT_TOOLS)
    print(f"\n{total - failures}/{total} tools passed.")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
