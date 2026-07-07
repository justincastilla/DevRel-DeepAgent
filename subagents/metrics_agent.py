"""
Metrics SubAgent - Specialized agent for GitHub repository metrics analysis.

System prompt lives in prompts/metrics_agent.py.
"""

from prompts import METRICS_AGENT_PROMPT
from tools import fetch_repo_metrics, store_research_snapshot, store_subagent_findings

metrics_subagent = {
    "name": "metrics-agent",
    "description": """Fetches and analyzes GitHub repository health metrics including stars, forks, commit velocity, and contributor patterns. Use this agent when you need quantitative data about a repository's health.""",
    "system_prompt": METRICS_AGENT_PROMPT,
    "tools": [fetch_repo_metrics, store_research_snapshot, store_subagent_findings],
}
