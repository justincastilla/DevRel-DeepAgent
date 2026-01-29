"""
Custom exceptions for DevRel Research Agent.
"""


class DevRelResearchError(Exception):
    """Base exception for all DevRel research errors."""
    pass


class GitHubAPIError(DevRelResearchError):
    """Raised when GitHub API requests fail."""
    pass


class RateLimitError(DevRelResearchError):
    """Raised when API rate limits are exceeded."""

    def __init__(self, message: str, retry_after: float = None):
        super().__init__(message)
        self.retry_after = retry_after  # Seconds until rate limit resets


class ElasticsearchError(DevRelResearchError):
    """Raised when Elasticsearch operations fail."""
    pass


class SubAgentError(DevRelResearchError):
    """Raised when a subagent fails to complete its task."""
    pass


class ConfigurationError(DevRelResearchError):
    """Raised when configuration is invalid or missing."""
    pass


class ScoringError(DevRelResearchError):
    """Raised when viability scoring fails."""
    pass


class SearchError(DevRelResearchError):
    """Raised when web search operations fail."""
    pass
