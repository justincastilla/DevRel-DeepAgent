"""
Elastic SubAgent - Queries Elasticsearch directly via native LangChain tools.

This subagent owns a set of read-only Elasticsearch tools and decides which to
call to satisfy a request. It talks to Elasticsearch directly (via the ES client
in tools/elasticsearch_tools.py) — it does NOT route through the Elastic Agent
Builder /converse endpoint. Every tool returns structured data (dicts/lists).

System prompt lives in prompts/elastic_agent.py.
"""

from prompts import ELASTIC_AGENT_PROMPT
from tools.elasticsearch_tools import (
    find_similar_technologies,
    get_trend_data,
    search_by_tags,
    compare_technologies,
)
from tools.elastic_search_tools import ELASTIC_WRAPPER_TOOLS

# The full read-only tool set for the elastic-agent subagent.
ELASTIC_SUBAGENT_TOOLS = [
    find_similar_technologies,
    get_trend_data,
    search_by_tags,
    compare_technologies,
    *ELASTIC_WRAPPER_TOOLS,
]

elastic_subagent = {
    "name": "elastic-agent",
    "description": """Retrieves technology-research data already stored in Elasticsearch.
Queries Elasticsearch directly via purpose-built tools (no external agent round-trip).
Use this agent when you need to:
- Find previously researched technologies via semantic search
- Retrieve historical trends and time-series metrics for a repo
- Get adoption signals (blog posts, case studies, job postings) for a repo
- Fetch past research reports (latest, or a recent one within an age window)
- List or search past technology discoveries
- Compare stored snapshots for multiple repos side-by-side
This agent reads EXISTING data only. It does not fetch fresh GitHub or web data,
and it does NOT check API caches (GitHub/web-search caching is handled in Redis
automatically inside the fetch tools).""",
    "system_prompt": ELASTIC_AGENT_PROMPT,
    "tools": ELASTIC_SUBAGENT_TOOLS,
}
