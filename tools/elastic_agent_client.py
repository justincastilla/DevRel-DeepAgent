"""
Elastic Agent Client - Invokes ES|QL tools on the Elastic serverless agent.

This module provides a client for calling ES|QL tools created in the
Elastic Agent Builder via the Kibana API.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from dotenv import load_dotenv

from utils.logging_utils import get_logger

# Load environment variables
load_dotenv()

logger = get_logger(__name__)


class ElasticAgentClient:
    """
    Client for invoking ES|QL tools on the Elastic serverless agent.

    This client communicates with the Kibana Agent Builder API to execute
    ES|QL queries through pre-defined tools.
    """

    def __init__(self):
        """Initialize the Elastic Agent client."""
        self.kibana_url = os.getenv("KIBANA_URL") or self._derive_kibana_url()
        self.api_key = os.getenv("KIBANA_API_KEY") or os.getenv("ELASTICSEARCH_API_KEY")

        if not self.kibana_url:
            raise ValueError("KIBANA_URL environment variable is required")
        if not self.api_key:
            raise ValueError("KIBANA_API_KEY or ELASTICSEARCH_API_KEY is required")

        # Ensure URL doesn't have trailing slash
        self.kibana_url = self.kibana_url.rstrip("/")

        self.headers = {
            "kbn-xsrf": "true",
            "Authorization": f"ApiKey {self.api_key}",
            "Content-Type": "application/json",
        }

        self._client = httpx.Client(
            timeout=60.0,
            limits=httpx.Limits(
                max_keepalive_connections=5,
                max_connections=10,
                keepalive_expiry=30.0,
            ),
        )
        logger.info(f"Elastic Agent Client initialized with Kibana URL: {self.kibana_url}")

    def _derive_kibana_url(self) -> Optional[str]:
        """Derive Kibana URL from Elasticsearch host if possible."""
        es_host = os.getenv("ELASTICSEARCH_HOST", "")
        if es_host:
            # Common pattern: ES on port 9243, Kibana on port 5601
            # Or for cloud: same host, different path
            if ":9243" in es_host:
                return es_host.replace(":9243", ":5601")
            elif ".es." in es_host:
                # Elastic Cloud pattern
                return es_host.replace(".es.", ".kb.")
        return None

    def invoke_tool(self, tool_id: str, params: dict) -> dict:
        """
        Invoke an ES|QL tool on the Elastic agent.

        Args:
            tool_id: The tool identifier (e.g., 'find-similar-technologies')
            params: Parameters to pass to the tool

        Returns:
            Tool response data

        Raises:
            ElasticAgentError: If the tool invocation fails
        """
        url = f"{self.kibana_url}/api/agent_builder/tools/_execute"

        # Log tool invocation at INFO level for CLI visibility
        param_summary = ", ".join(f"{k}={str(v)[:30]}" for k, v in params.items())
        logger.info(f"[ELASTIC TOOL] Invoking: {tool_id} ({param_summary})")

        try:
            response = self._client.post(
                url,
                headers=self.headers,
                json={
                    "tool_id": tool_id,
                    "tool_params": params,
                },
            )

            if response.status_code == 200:
                result = response.json()
                # Log result summary
                result_count = len(result.get('results', result.get('data', []))) if isinstance(result, dict) else 0
                logger.info(f"[ELASTIC TOOL] {tool_id} returned {result_count} results")
                return result
            elif response.status_code == 404:
                raise ElasticAgentError(
                    f"Tool '{tool_id}' not found. Ensure it's created in the Agent Builder."
                )
            else:
                error_detail = response.json() if response.content else {}
                raise ElasticAgentError(
                    f"Tool invocation failed: HTTP {response.status_code} - {error_detail}"
                )

        except httpx.RequestError as e:
            logger.error(f"Request error invoking tool '{tool_id}': {e}")
            raise ElasticAgentError(f"Request failed: {e}")

    def check_tool_exists(self, tool_id: str) -> bool:
        """Check if a tool exists in the Agent Builder."""
        tools = self.list_tools()
        return any(t.get("id") == tool_id for t in tools)

    def list_tools(self) -> list[dict]:
        """List all tools available in the Agent Builder."""
        url = f"{self.kibana_url}/api/agent_builder/tools"

        try:
            response = self._client.get(url, headers=self.headers)
            if response.status_code == 200:
                data = response.json()
                # Handle various response formats
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and "results" in data:
                    return data["results"]
                elif isinstance(data, dict) and "tools" in data:
                    return data["tools"]
                elif isinstance(data, dict):
                    return [data]
        except httpx.RequestError as e:
            logger.error(f"Failed to list tools: {e}")

        return []

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb):
        self.close()


class ElasticAgentError(Exception):
    """Exception raised for Elastic Agent client errors."""
    pass


# Singleton client instance
_client: Optional[ElasticAgentClient] = None


def get_elastic_agent_client() -> ElasticAgentClient:
    """Get the singleton Elastic Agent client instance."""
    global _client
    if _client is None:
        _client = ElasticAgentClient()
    return _client


# =============================================================================
# Helper Functions for Date Parameters
# =============================================================================

def days_ago_iso(days: int) -> str:
    """
    Convert 'days ago' to ISO format date string.

    ES|QL tool parameters require ISO date strings, not relative dates.

    Args:
        days: Number of days in the past

    Returns:
        ISO format date string (e.g., '2024-10-01T00:00:00Z')
    """
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.strftime("%Y-%m-%dT00:00:00Z")


def hours_ago_iso(hours: int) -> str:
    """
    Convert 'hours ago' to ISO format date string.

    Args:
        hours: Number of hours in the past

    Returns:
        ISO format date string
    """
    dt = datetime.now(timezone.utc) - timedelta(hours=hours)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
