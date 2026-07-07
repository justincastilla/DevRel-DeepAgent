"""
Sentiment SubAgent - Specialized agent for community sentiment analysis.

System prompt lives in prompts/sentiment_agent.py.
"""

from prompts import SENTIMENT_AGENT_PROMPT
from tools import (
    fetch_recent_issues,
    fetch_repo_discussions,
    store_subagent_findings,
)

sentiment_subagent = {
    "name": "sentiment-agent",
    "description": """Analyzes GitHub issues and discussions to assess community health, maintainer responsiveness, and identify red flags. Use when you need qualitative assessment of a project's community.""",
    "system_prompt": SENTIMENT_AGENT_PROMPT,
    "tools": [
        fetch_recent_issues,
        fetch_repo_discussions,
        store_subagent_findings,
    ],
}
