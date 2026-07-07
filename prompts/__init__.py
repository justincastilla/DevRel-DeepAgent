"""
Prompts for the DevRel Research Agent.

One module per prompt owner:
- orchestrator.py     — main agent instructions, report templates, get_system_prompt()
- metrics_agent.py    — metrics-agent system prompt
- sentiment_agent.py  — sentiment-agent system prompt
- web_agent.py        — web-research-agent system prompt
- elastic_agent.py    — elastic-agent system prompt

`from prompts import get_system_prompt` keeps working exactly as it did when
prompts.py was a single module.
"""

from .orchestrator import (
    DEVREL_RESEARCH_INSTRUCTIONS,
    SUBAGENT_DELEGATION_INSTRUCTIONS,
    get_system_prompt,
)
from .metrics_agent import METRICS_AGENT_PROMPT
from .sentiment_agent import SENTIMENT_AGENT_PROMPT
from .web_agent import WEB_AGENT_PROMPT
from .elastic_agent import ELASTIC_AGENT_PROMPT

__all__ = [
    "DEVREL_RESEARCH_INSTRUCTIONS",
    "SUBAGENT_DELEGATION_INSTRUCTIONS",
    "get_system_prompt",
    "METRICS_AGENT_PROMPT",
    "SENTIMENT_AGENT_PROMPT",
    "WEB_AGENT_PROMPT",
    "ELASTIC_AGENT_PROMPT",
]
