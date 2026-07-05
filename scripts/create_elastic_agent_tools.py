"""
Create (or update) the custom ES|QL tools in Elastic Agent Builder.

The tool definitions live in `elastic_agent_tools.md` as JSON bodies following
each `POST kbn:/api/agent_builder/tools` command. This script extracts those
JSON bodies and creates the tools via the Kibana API, so you don't have to paste
each one into Dev Tools by hand.

Run this BEFORE scripts/create_elastic_agent.py — the agent references these
tool IDs and cannot be created until they exist.

Usage:
    python scripts/create_elastic_agent_tools.py            # create all
    python scripts/create_elastic_agent_tools.py --dry-run  # parse only, no writes
"""

import json
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import config  # noqa: E402

DOC_PATH = Path(__file__).parent.parent / "elastic_agent_tools.md"
POST_MARKER = "POST kbn:/api/agent_builder/tools"


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


# The doc documents params using ES|QL column types, but the Agent Builder API
# accepts only: string, integer, float, boolean, date, array. Map the ES|QL-only
# spellings onto the API enum; valid types pass through unchanged.
_PARAM_TYPE_MAP = {"text": "string", "keyword": "string", "double": "float", "long": "integer"}


def _normalize_param_types(tool: dict) -> dict:
    """Rewrite param types onto the Agent Builder API enum."""
    params = tool.get("configuration", {}).get("params", {})
    for spec in params.values():
        if isinstance(spec, dict) and spec.get("type") in _PARAM_TYPE_MAP:
            spec["type"] = _PARAM_TYPE_MAP[spec["type"]]
    return tool


def parse_tool_defs(doc: str) -> list[dict]:
    """Parse tool definitions from ```json fenced blocks that carry the POST marker.

    Each real tool block looks like:
        ```json
        POST kbn:/api/agent_builder/tools
        { ...tool json... }
        ```
    We take the JSON object after the POST line and require an "id" + "type" so
    example snippets can never sneak in.
    """
    defs = []
    for block in re.findall(r"```json\s*(.*?)```", doc, re.DOTALL):
        if POST_MARKER not in block:
            continue
        json_text = block[block.index("{"):].rstrip()
        obj = json.loads(json_text)
        if "id" in obj and obj.get("type") == "esql":
            defs.append(_normalize_param_types(obj))
    return defs


def upsert_tool(client: httpx.Client, tool: dict) -> str:
    """Create the tool; if it already exists, update it in place. Returns status word."""
    tool_id = tool["id"]
    resp = client.post("/api/agent_builder/tools", json=tool)
    if resp.status_code in (200, 201):
        return "created"
    # Already exists → update via PUT on the specific id.
    body = resp.text.lower()
    if resp.status_code in (400, 409) and ("exist" in body or "conflict" in body):
        # The update endpoint rejects immutable fields ('id', 'type').
        update = {k: v for k, v in tool.items() if k not in ("id", "type")}
        put = client.put(f"/api/agent_builder/tools/{tool_id}", json=update)
        if put.status_code in (200, 201):
            return "updated"
        return f"FAILED update ({put.status_code}): {put.text[:200]}"
    return f"FAILED ({resp.status_code}): {resp.text[:200]}"


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    doc = DOC_PATH.read_text(encoding="utf-8")
    tools = parse_tool_defs(doc)

    print(f"\nParsed {len(tools)} tool definitions from {DOC_PATH.name}:")
    for t in tools:
        print(f"  • {t['id']}")

    if dry_run:
        print("\n--dry-run: no changes made.")
        return

    print(f"\nKibana: {config.KIBANA_URL}\nCreating tools...\n")
    client = get_client()
    results = {}
    for t in tools:
        status = upsert_tool(client, t)
        results[t["id"]] = status
        symbol = "[OK]" if status in ("created", "updated") else "[FAIL]"
        print(f"  {symbol} {t['id']}: {status}")

    ok = sum(1 for s in results.values() if s in ("created", "updated"))
    print(f"\n{ok}/{len(tools)} tools ready.")
    if ok != len(tools):
        sys.exit(1)


if __name__ == "__main__":
    main()
