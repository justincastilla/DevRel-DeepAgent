"""
Web Research SubAgent - Specialized agent for adoption research.

System prompt lives in prompts/web_agent.py.
"""

from utils.logging_utils import get_logger
from prompts import WEB_AGENT_PROMPT
from tools.web_tools import tavily_search, record_adoption_signal  # noqa: F401
from tools import store_subagent_findings

logger = get_logger(__name__)


web_subagent = {
    "name": "web-research-agent",
    "description": """Searches the web for real-world adoption signals: blog posts, conference talks, production case studies, and job postings. Use when you need external validation of a technology's traction.""",
    "system_prompt": WEB_AGENT_PROMPT,
    "tools": [tavily_search, record_adoption_signal, store_subagent_findings],
}
