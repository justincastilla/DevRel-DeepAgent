"""
Elastic Subagent Tools - LangChain tools for the Elastic subagent.

Communicates with the Elastic Agent Builder via the /converse endpoint,
letting the agent select and execute its own ES|QL tools internally.
"""

from langchain_core.tools import tool

from .elastic_agent_client import (
    get_elastic_agent_client,
    ElasticAgentError,
)
from utils.logging_utils import get_logger

logger = get_logger(__name__)


@tool
def ask_elastic_agent(query: str, conversation_id: str = None) -> str:
    """
    Send a natural-language request to the Elastic Agent and return its response.

    The agent has access to all ES|QL tools for searching, retrieving, and
    analysing technology research data stored in Elasticsearch. It will select
    the appropriate tool(s) and return a synthesised answer.

    Use this tool for any data retrieval from Elasticsearch, including:
    - Finding similar technologies via semantic search
    - Retrieving historical snapshots, trends, and time-series data
    - Getting adoption signals (blog posts, case studies, job postings)
    - Fetching past research reports or technology discoveries
    - Comparing repository data side-by-side

    Args:
        query: Natural-language description of what data you need.
               Be specific: include repo names, time ranges, and what you want.
               Examples:
                 "Get the latest research report for elastic/elasticsearch"
                 "Find technologies similar to 'AI agent orchestration frameworks'"
                 "Get adoption signals for langchain-ai/langgraph from the last 90 days"
                 "Check if there is a cached research report for crewAIInc/crewAI from the last 7 days"
                 "Get trend data for microsoft/autogen over the last 6 months"
        conversation_id: Optional. Pass the conversation_id returned from a previous
                         call to continue a multi-turn conversation with the agent.

    Returns:
        The agent's response as a string, containing the requested data and insights.
    """
    client = get_elastic_agent_client()
    try:
        result = client.chat(input=query, conversation_id=conversation_id)
        response = result.get("response", "")
        if not response:
            return "The agent returned an empty response."
        return response
    except ElasticAgentError as e:
        logger.error(f"Elastic agent chat failed: {e}")
        return f"Error communicating with Elastic Agent: {e}"


# The single tool exported for use by the elastic-agent subagent
ELASTIC_SUBAGENT_TOOLS = [ask_elastic_agent]
