"""
Configuration module for DevRel Research Agent.
Loads environment variables and provides centralized configuration.
"""

import os
import re
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

# Keys that should never be logged in plain text
_SENSITIVE_KEYS = {
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "TAVILY_API_KEY",
    "GITHUB_TOKEN",
    "GITHUB_API_KEY",
    "ELASTICSEARCH_API_KEY",
    "KIBANA_API_KEY",
    "LANGSMITH_API_KEY",
}

# Patterns that look like API keys (for sanitizing arbitrary strings)
_API_KEY_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),  # OpenAI-style
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),  # GitHub PAT
    re.compile(r"gho_[a-zA-Z0-9]{36}"),  # GitHub OAuth
    re.compile(r"github_pat_[a-zA-Z0-9_]{22,}"),  # GitHub fine-grained PAT
    # Base64-style keys (e.g. Elasticsearch API keys). The lookarounds require
    # the match to be a standalone token (not a slice of a longer word), which
    # avoids mangling ordinary long strings like report text or IDs in logs.
    re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/])"),
    re.compile(r"tvly-[a-zA-Z0-9]{20,}"),  # Tavily-style
]


class Config:
    """Central configuration class."""

    # LLM Provider
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    ANTHROPIC_FOUNDRY_RESOURCE = os.getenv("ANTHROPIC_FOUNDRY_RESOURCE")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
    AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
    AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")

    # Web Search
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

    # GitHub API
    GITHUB_TOKEN = os.getenv("GITHUB_API_KEY")  # Using GITHUB_API_KEY from .env

    # Elasticsearch
    ELASTICSEARCH_URL = os.getenv("ELASTICSEARCH_HOST")  # Using ELASTICSEARCH_HOST from .env
    ELASTICSEARCH_API_KEY = os.getenv("ELASTICSEARCH_API_KEY")

    # Redis (local cache backend)
    # Caching moved from Elasticsearch to a locally hosted Redis instance.
    # Defaults point at a Redis running on the same machine / docker-compose.
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_DB = int(os.getenv("REDIS_DB", "0"))
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")  # optional; leave unset for local dev

    # Cache time-to-live values, in seconds. Centralized here so the read
    # window and the expiry window can never drift apart. Redis enforces these
    # as native key expirations, so there is no separate cleanup job.
    CACHE_TTL_WEB_SEARCH = int(os.getenv("CACHE_TTL_WEB_SEARCH", str(7 * 24 * 3600)))     # 7 days
    CACHE_TTL_GITHUB_METRICS = int(os.getenv("CACHE_TTL_GITHUB_METRICS", str(24 * 3600)))  # 24 hours
    CACHE_TTL_GITHUB_DATA = int(os.getenv("CACHE_TTL_GITHUB_DATA", str(8 * 3600)))         # 8 hours

    # Kibana (for Elastic Agent Builder)
    KIBANA_URL = os.getenv("KIBANA_URL")  # Optional - derived from ELASTICSEARCH_HOST if not set
    KIBANA_API_KEY = os.getenv("KIBANA_API_KEY")  # Optional - uses ELASTICSEARCH_API_KEY if not set
    ELASTIC_AGENT_ID = os.getenv("ELASTIC_AGENT_ID")  # Agent ID for /converse endpoint

    # Observability
    LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY")
    LANGCHAIN_PROJECT = os.getenv("LANGCHAIN_PROJECT", "devrel-research-agent")
    LANGCHAIN_TRACING_V2 = os.getenv("LANGCHAIN_TRACING_V2", "true")

    # Agent Configuration
    MAX_CONCURRENT_SUBAGENTS = 3
    MAX_ITERATIONS_PER_SUBAGENT = 5
    # LangGraph recursion limit: each subagent tool call + orchestrator step
    # counts toward this. 4 subagents × ~10 steps + orchestrator overhead = ~60
    # for a single eval; comparisons of 3 repos can hit ~100+.
    # GPT models take more steps than Claude, so they need a higher limit.
    RECURSION_LIMIT = int(os.getenv("RECURSION_LIMIT", "150"))

    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = os.getenv("LOG_FILE", "devrel_research.log")

    @classmethod
    def validate(cls) -> list[str]:
        """
        Validate that required environment variables are set.
        Returns list of missing variables.
        """
        missing = []

        required_vars = {
            "ANTHROPIC_API_KEY": cls.ANTHROPIC_API_KEY,
            "TAVILY_API_KEY": cls.TAVILY_API_KEY,
            "GITHUB_TOKEN": cls.GITHUB_TOKEN,
            "ELASTICSEARCH_URL": cls.ELASTICSEARCH_URL,
            "ELASTICSEARCH_API_KEY": cls.ELASTICSEARCH_API_KEY,
        }

        for var_name, var_value in required_vars.items():
            if not var_value:
                missing.append(var_name)

        return missing

    @staticmethod
    def mask_value(value: Optional[str], visible_chars: int = 4) -> str:
        """
        Mask a sensitive value, showing only the first few characters.

        Args:
            value: The sensitive value to mask
            visible_chars: Number of characters to show at the start

        Returns:
            Masked string like "sk-a1***" or "[NOT SET]"
        """
        if not value:
            return "[NOT SET]"
        if len(value) <= visible_chars:
            return "***"
        return f"{value[:visible_chars]}***"

    @classmethod
    def get_config_summary(cls) -> dict:
        """
        Get a safe-to-log summary of configuration.
        All sensitive values are masked.

        Returns:
            Dictionary with configuration status (masked values)
        """
        return {
            # API Keys (masked)
            "ANTHROPIC_API_KEY": cls.mask_value(cls.ANTHROPIC_API_KEY),
            "OPENAI_API_KEY": cls.mask_value(cls.OPENAI_API_KEY),
            "TAVILY_API_KEY": cls.mask_value(cls.TAVILY_API_KEY),
            "GITHUB_TOKEN": cls.mask_value(cls.GITHUB_TOKEN),
            "ELASTICSEARCH_API_KEY": cls.mask_value(cls.ELASTICSEARCH_API_KEY),
            "KIBANA_API_KEY": cls.mask_value(cls.KIBANA_API_KEY),
            "LANGSMITH_API_KEY": cls.mask_value(cls.LANGSMITH_API_KEY),
            # Non-sensitive values (shown in full)
            "ANTHROPIC_FOUNDRY_RESOURCE": cls.ANTHROPIC_FOUNDRY_RESOURCE or "[NOT SET]",
            "ELASTICSEARCH_URL": cls.ELASTICSEARCH_URL or "[NOT SET]",
            "REDIS_HOST": cls.REDIS_HOST,
            "REDIS_PORT": cls.REDIS_PORT,
            "KIBANA_URL": cls.KIBANA_URL or "[NOT SET]",
            "LANGCHAIN_PROJECT": cls.LANGCHAIN_PROJECT,
            "LOG_LEVEL": cls.LOG_LEVEL,
            "MAX_CONCURRENT_SUBAGENTS": cls.MAX_CONCURRENT_SUBAGENTS,
            "MAX_ITERATIONS_PER_SUBAGENT": cls.MAX_ITERATIONS_PER_SUBAGENT,
        }

    @classmethod
    def is_sensitive_key(cls, key_name: str) -> bool:
        """
        Check if a configuration key name is sensitive.

        Args:
            key_name: The name of the configuration key

        Returns:
            True if the key should be treated as sensitive
        """
        return key_name.upper() in _SENSITIVE_KEYS


def sanitize_for_logging(text: str) -> str:
    """
    Sanitize a string by masking any detected API keys.
    Use this before logging any string that might contain credentials.

    Args:
        text: The text to sanitize

    Returns:
        Text with API keys masked
    """
    if not text:
        return text

    result = text
    for pattern in _API_KEY_PATTERNS:
        result = pattern.sub(lambda m: f"{m.group(0)[:4]}***", result)

    return result


# Create singleton instance
config = Config()
