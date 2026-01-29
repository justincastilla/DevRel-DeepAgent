"""
Retry utilities with exponential backoff.
"""

from functools import wraps
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from exceptions import GitHubAPIError, ElasticsearchError, SearchError
from utils.logging_utils import get_logger

logger = get_logger(__name__)


def with_retry(max_attempts: int = 3, exceptions: tuple = None):
    """
    Decorator to add retry logic with exponential backoff.

    Args:
        max_attempts: Maximum number of retry attempts
        exceptions: Tuple of exception types to retry on

    Returns:
        Decorated function with retry logic
    """
    if exceptions is None:
        exceptions = (GitHubAPIError, ElasticsearchError, SearchError)

    def decorator(func):
        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            retry=retry_if_exception_type(exceptions),
            reraise=True,
        )
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except exceptions as e:
                logger.warning(f"Retrying {func.__name__} after error: {e}")
                raise

        return wrapper

    return decorator
