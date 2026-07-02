"""
GitHub API tools for fetching repository metrics, issues, and discussions.
"""

import atexit
import threading
import time
from datetime import datetime, timedelta
from typing import Optional
import httpx
from langchain_core.tools import tool

from config import config
from exceptions import GitHubAPIError, RateLimitError, RepositoryNotFoundError
from utils.logging_utils import get_logger
from utils.retry_utils import with_retry
from tools.cache import (
    get_cached_github_metrics,
    store_github_metrics_cache,
    get_cached_github_data,
    store_github_data_cache,
)
from tools.elasticsearch_tools import (
    store_timeseries_snapshot,
    store_commit_history,
)
from tools.web_tools import tavily_search

logger = get_logger(__name__)

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"


def parse_github_datetime(date_str: str) -> datetime:
    """
    Parse a GitHub API datetime string to a naive UTC datetime.

    GitHub returns ISO 8601 format with 'Z' suffix (e.g., '2025-01-28T12:00:00Z').

    Args:
        date_str: ISO 8601 datetime string from GitHub API

    Returns:
        Naive datetime object in UTC
    """
    return datetime.fromisoformat(date_str.replace("Z", "+00:00")).replace(tzinfo=None)


# =============================================================================
# HTTP Connection Pool (Singleton)
# =============================================================================

_github_client: Optional[httpx.Client] = None


def get_github_client() -> httpx.Client:
    """
    Get the singleton GitHub HTTP client with connection pooling.

    The client is configured with:
    - Connection pooling for HTTP/1.1 and HTTP/2
    - Keep-alive connections
    - Reasonable timeouts
    - Automatic retry on connection errors

    Returns:
        Configured httpx.Client instance
    """
    global _github_client

    if _github_client is None:
        _github_client = httpx.Client(
            # Connection pool settings
            limits=httpx.Limits(
                max_keepalive_connections=5,
                max_connections=10,
                keepalive_expiry=30.0,
            ),
            # Enable HTTP/2 for better performance
            http2=True,
            # Timeouts
            timeout=httpx.Timeout(
                connect=10.0,
                read=30.0,
                write=10.0,
                pool=5.0,
            ),
            # Default headers for GitHub API
            headers={
                "Accept": "application/json",
                "User-Agent": "DevRel-Research-Agent/1.0",
            },
        )
        logger.debug("GitHub HTTP client initialized with connection pooling")

    return _github_client


def close_github_client() -> None:
    """
    Close the GitHub HTTP client and release connections.
    Call this during application shutdown.
    """
    global _github_client

    if _github_client is not None:
        _github_client.close()
        _github_client = None
        logger.debug("GitHub HTTP client closed")


# Register cleanup handler for graceful shutdown
atexit.register(close_github_client)


# =============================================================================
# Rate Limiter (Token Bucket Algorithm)
# =============================================================================


class RateLimiter:
    """
    Token bucket rate limiter for GitHub API calls.

    GitHub allows 5000 requests/hour for authenticated users.
    We use a conservative limit of 1000/hour to leave headroom
    for other tools and avoid hitting the limit.

    The token bucket algorithm allows bursts while maintaining
    a sustainable average rate.
    """

    def __init__(
        self,
        max_calls_per_hour: int = 1000,
        warning_threshold: float = 0.2,
    ):
        """
        Initialize the rate limiter.

        Args:
            max_calls_per_hour: Maximum API calls allowed per hour (default 1000)
            warning_threshold: Log warning when this fraction of calls remain (default 0.2)
        """
        self.max_calls_per_hour = max_calls_per_hour
        self.warning_threshold = warning_threshold

        # Token bucket state
        self._tokens = float(max_calls_per_hour)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

        # Tracking
        self._total_calls = 0
        self._blocked_calls = 0

        # Refill rate: tokens per second
        self._refill_rate = max_calls_per_hour / 3600.0

        logger.debug(
            f"Rate limiter initialized: {max_calls_per_hour} calls/hour "
            f"({self._refill_rate:.4f} tokens/sec)"
        )

    def _refill_tokens(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            self.max_calls_per_hour, self._tokens + (elapsed * self._refill_rate)
        )
        self._last_refill = now

    def acquire(self, timeout: float = 30.0) -> bool:
        """
        Acquire a token to make an API call.

        Blocks until a token is available or timeout is reached.

        Args:
            timeout: Maximum seconds to wait for a token

        Returns:
            True if token acquired, False if timeout

        Raises:
            RateLimitError: If rate limit is severely exceeded
        """
        start_time = time.monotonic()

        while True:
            with self._lock:
                self._refill_tokens()

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    self._total_calls += 1

                    # Check warning threshold
                    remaining_fraction = self._tokens / self.max_calls_per_hour
                    if remaining_fraction < self.warning_threshold:
                        logger.warning(
                            f"GitHub API rate limit warning: {self._tokens:.0f} "
                            f"calls remaining ({remaining_fraction:.1%})"
                        )

                    return True

                # Calculate wait time for next token
                wait_time = (1.0 - self._tokens) / self._refill_rate

            # Check timeout
            elapsed = time.monotonic() - start_time
            if elapsed + wait_time > timeout:
                self._blocked_calls += 1
                logger.error(
                    f"Rate limit timeout: waited {elapsed:.1f}s, "
                    f"need {wait_time:.1f}s more for next token"
                )
                return False

            # Wait for tokens to refill
            time.sleep(min(wait_time, timeout - elapsed))

    def get_remaining_calls(self) -> int:
        """
        Get the number of remaining API calls.

        Returns:
            Approximate number of calls available
        """
        with self._lock:
            self._refill_tokens()
            return int(self._tokens)

    def get_stats(self) -> dict:
        """
        Get rate limiter statistics.

        Returns:
            Dictionary with usage statistics
        """
        with self._lock:
            self._refill_tokens()
            return {
                "remaining_calls": int(self._tokens),
                "max_calls_per_hour": self.max_calls_per_hour,
                "total_calls_made": self._total_calls,
                "blocked_calls": self._blocked_calls,
                "utilization": 1.0 - (self._tokens / self.max_calls_per_hour),
            }

    def sync_from_api(self, remaining: int, reset_timestamp: int) -> None:
        """
        Sync the local token bucket with GitHub's actual rate limit headers.

        Called after every successful GraphQL response to keep the local
        bucket accurate instead of relying solely on our own counting.

        Args:
            remaining: Value of X-RateLimit-Remaining response header
            reset_timestamp: Value of X-RateLimit-Reset header (Unix timestamp)
        """
        with self._lock:
            new_tokens = float(min(remaining, self.max_calls_per_hour))
            if new_tokens < self._tokens:
                # API says we've used more than we tracked — sync down to be safe
                logger.debug(
                    f"Rate limiter synced from API headers: "
                    f"{self._tokens:.0f} → {new_tokens:.0f} remaining "
                    f"(reset at {reset_timestamp})"
                )
                self._tokens = new_tokens
                self._last_refill = time.monotonic()

    def reset(self) -> None:
        """Reset the rate limiter to full capacity."""
        with self._lock:
            self._tokens = float(self.max_calls_per_hour)
            self._last_refill = time.monotonic()
            logger.debug("Rate limiter reset to full capacity")


# Singleton rate limiter instance
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get the singleton rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


def get_remaining_github_calls() -> int:
    """
    Get the number of remaining GitHub API calls.

    Returns:
        Number of calls available before rate limiting kicks in
    """
    return get_rate_limiter().get_remaining_calls()


def get_github_rate_limit_stats() -> dict:
    """
    Get GitHub API rate limit statistics.

    Returns:
        Dictionary with rate limit stats
    """
    return get_rate_limiter().get_stats()


@with_retry(max_attempts=3, exceptions=(GitHubAPIError,))
def _execute_graphql(query: str, variables: dict) -> dict:
    """
    Execute a GitHub GraphQL query with retry logic.

    Uses connection pooling and rate limiting for reliable operation.

    Args:
        query: GraphQL query string
        variables: Query variables

    Returns:
        Response data dictionary

    Raises:
        GitHubAPIError: If the request fails
        RateLimitError: If rate limit is exceeded
    """
    if not config.GITHUB_TOKEN:
        raise GitHubAPIError("GITHUB_TOKEN not configured")

    # Acquire rate limit token before making request
    rate_limiter = get_rate_limiter()
    if not rate_limiter.acquire(timeout=60.0):
        raise RateLimitError(
            "GitHub API rate limit exceeded. Please wait before making more requests.",
            retry_after=3600.0 / rate_limiter.max_calls_per_hour,
        )

    # Get pooled client
    client = get_github_client()

    # Request-specific headers (Authorization with token)
    headers = {
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        response = client.post(
            GITHUB_GRAPHQL_URL,
            json={"query": query, "variables": variables},
            headers=headers,
        )

        # Handle GitHub's rate limit response (403 with specific message or 429)
        if response.status_code == 429 or (
            response.status_code == 403 and "rate limit" in response.text.lower()
        ):
            # Parse retry-after header if available
            retry_after = response.headers.get("Retry-After")
            retry_seconds = float(retry_after) if retry_after else 60.0

            logger.warning(
                f"GitHub API rate limit hit (HTTP {response.status_code}). "
                f"Retry after {retry_seconds}s"
            )
            raise RateLimitError(
                f"GitHub API rate limit exceeded (HTTP {response.status_code})",
                retry_after=retry_seconds,
            )

        response.raise_for_status()
        data = response.json()

        # Sync rate limiter from actual API quota headers (more accurate than counting)
        remaining_hdr = response.headers.get("X-RateLimit-Remaining")
        reset_hdr = response.headers.get("X-RateLimit-Reset")
        if remaining_hdr is not None and reset_hdr is not None:
            try:
                rate_limiter.sync_from_api(int(remaining_hdr), int(reset_hdr))
            except (ValueError, TypeError):
                pass

        if "errors" in data:
            error_msg = "; ".join([e.get("message", str(e)) for e in data["errors"]])
            # "Not found" is permanent — raise immediately without retry
            if any(
                phrase in error_msg.lower()
                for phrase in ("could not resolve to a repository", "not found", "does not exist")
            ):
                raise RepositoryNotFoundError(f"Repository not found: {error_msg}")
            raise GitHubAPIError(f"GraphQL errors: {error_msg}")

        return data
    except httpx.HTTPError as e:
        logger.error(f"GitHub API request failed: {e}")
        raise GitHubAPIError(f"GitHub API request failed: {e}") from e


def _fetch_repo_metrics_from_web(owner: str, repo: str) -> dict:
    """
    Fallback: Fetch repository metrics from web sources when GitHub API is blocked.

    Uses Tavily search to gather publicly available information about the repository.
    This provides approximate metrics when the API is inaccessible (e.g., SAML enforcement).

    Args:
        owner: Repository owner
        repo: Repository name

    Returns:
        Dictionary with approximate metrics gathered from web sources
    """
    import re

    repo_full = f"{owner}/{repo}"
    github_url = f"https://github.com/{repo_full}"

    logger.info(f"Fetching metrics from web for {repo_full} (SAML fallback)")

    # Single composite query instead of 3 separate calls
    composite_query = (
        f"{owner}/{repo} GitHub repository stars forks contributors "
        f"programming language open source"
    )
    web_findings = []
    try:
        results = tavily_search.invoke({"query": composite_query, "max_results": 5})
        if results and "results" in results:
            web_findings.extend(results["results"])
    except Exception as e:
        logger.warning(f"Web search fallback failed for '{repo_full}': {e}")

    # Combine all text for parsing
    all_text = " ".join(
        [r.get("content", "") + " " + r.get("snippet", "") for r in web_findings]
    )

    # Parse metrics from web text
    metrics = {
        "stars": _parse_number_from_text(
            all_text, r"(\d{1,3}(?:,\d{3})*|\d+\.?\d*[kKmM]?)\s*(?:stars?|⭐)"
        ),
        "forks": _parse_number_from_text(
            all_text, r"(\d{1,3}(?:,\d{3})*|\d+\.?\d*[kKmM]?)\s*forks?"
        ),
        "open_issues": _parse_number_from_text(
            all_text, r"(\d{1,3}(?:,\d{3})*)\s*(?:open\s+)?issues?"
        ),
        "contributors": _parse_number_from_text(
            all_text, r"(\d{1,3}(?:,\d{3})*|\d+)\s*contributors?"
        ),
    }

    # Set defaults for missing values
    for key in ["stars", "forks", "open_issues", "contributors"]:
        if metrics[key] is None:
            metrics[key] = 0

    result = {
        "repo": repo_full,
        "github_url": github_url,
        "description": f"Repository info gathered from web (API access restricted)",
        "license": "Unknown (check GitHub page)",
        "source": "web_fallback",
        "metrics_approximate": True,
        "metrics": {
            "stars": metrics["stars"],
            "forks": metrics["forks"],
            "open_issues": metrics["open_issues"],
            "closed_issues": 0,  # Can't determine from web
            "open_prs": 0,
            "merged_prs": 0,
            "contributors": metrics["contributors"],
        },
        "derived": {
            "repo_age_days": 0,  # Unknown
            "stars_per_month": 0,
            "commits_7d": 0,
            "commits_30d": 0,
            "commits_90d": 0,
            "unique_authors_7d": 0,
            "unique_authors_30d": 0,
            "issue_close_rate": 0,
            "pr_merge_rate": 0,
        },
        "recent_releases": [],
        "web_sources": len(web_findings),
        "note": "Metrics are approximate. For accurate data, authorize your GitHub PAT for this organization's SAML SSO.",
    }

    logger.info(
        f"Web fallback for {repo_full}: ~{metrics['stars']} stars from {len(web_findings)} sources"
    )
    return result


def _parse_number_from_text(text: str, pattern: str) -> Optional[int]:
    """Parse a number from text using a regex pattern. Handles k/K/m/M suffixes."""
    import re

    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None

    num_str = match.group(1).replace(",", "").lower()

    try:
        if "k" in num_str:
            return int(float(num_str.replace("k", "")) * 1000)
        elif "m" in num_str:
            return int(float(num_str.replace("m", "")) * 1000000)
        else:
            return int(float(num_str))
    except (ValueError, TypeError):
        return None


@tool
def fetch_repo_metrics(owner: str, repo: str, cache_hours: int = 24) -> dict:
    """
    Fetch GitHub repository health metrics via GraphQL API.
    Results are cached to reduce API calls.
    Falls back to web search if API access is blocked (e.g., SAML enforcement).

    Returns comprehensive metrics including:
    - Star count and fork count
    - Open issues and pull requests
    - Recent commit activity (last 100 commits)
    - Contributor count
    - License and description

    Args:
        owner: Repository owner (e.g., "langchain-ai")
        repo: Repository name (e.g., "deepagents")
        cache_hours: Use cached results if less than this many hours old (default 24)

    Returns:
        Dictionary with structured metrics and derived calculations
    """
    repo_full = f"{owner}/{repo}"

    # Check cache first
    cached = get_cached_github_metrics(repo_full)
    if cached:
        logger.info(f"Using cached metrics for {repo_full}")
        metrics = cached["metrics"]
        derived = cached.get("derived", {})
        # Safety net: if a cache entry stored raw counts but no rates, compute
        # them here so downstream scoring always gets valid values.
        if not derived.get("issue_close_rate"):
            total_i = metrics.get("open_issues", 0) + metrics.get("closed_issues", 0)
            if total_i > 0:
                derived["issue_close_rate"] = round(metrics.get("closed_issues", 0) / total_i * 100, 1)
        if not derived.get("pr_merge_rate"):
            total_p = metrics.get("open_prs", 0) + metrics.get("merged_prs", 0)
            if total_p > 0:
                derived["pr_merge_rate"] = round(metrics.get("merged_prs", 0) / total_p * 100, 1)
        return {
            "repo": repo_full,
            "metrics": metrics,
            "derived": derived,
            "cached": True,
        }

    logger.info(f"Fetching fresh metrics for {repo_full}")

    query = """
    query($owner: String!, $repo: String!) {
      repository(owner: $owner, name: $repo) {
        name
        description
        stargazerCount
        forkCount
        createdAt
        updatedAt
        licenseInfo { name }
        issues(states: OPEN) { totalCount }
        closedIssues: issues(states: CLOSED) { totalCount }
        pullRequests(states: OPEN) { totalCount }
        mergedPRs: pullRequests(states: MERGED) { totalCount }
        defaultBranchRef {
          target {
            ... on Commit {
              history(first: 100) {
                totalCount
                edges {
                  node {
                    committedDate
                    author { user { login } }
                  }
                }
              }
            }
          }
        }
        mentionableUsers(first: 1) { totalCount }
        releases(first: 5) {
          nodes {
            tagName
            publishedAt
          }
        }
      }
    }
    """

    try:
        result = _execute_graphql(query, {"owner": owner, "repo": repo})
    except RepositoryNotFoundError as e:
        logger.warning(f"Repository {repo_full} not found on GitHub: {e}")
        return {
            "repo": repo_full,
            "error": f"Repository '{repo_full}' not found on GitHub. It may have been renamed, deleted, or the name is incorrect.",
            "cached": False,
        }
    except GitHubAPIError as e:
        # Check if this is a SAML enforcement error
        if "SAML" in str(e) or "organization" in str(e).lower():
            logger.warning(
                f"GitHub API blocked by SAML for {repo_full}, falling back to web search"
            )
            return _fetch_repo_metrics_from_web(owner, repo)
        raise

    repo_data = result.get("data", {}).get("repository", {})

    if not repo_data:
        logger.warning(f"Repository {owner}/{repo} not found")
        return {"error": f"Repository {owner}/{repo} not found"}

    # Extract commit history for analysis
    # Parse dates once upfront for efficiency (avoid re-parsing in each calculation)
    commits = []
    commit_history = (
        repo_data.get("defaultBranchRef", {}).get("target", {}).get("history", {})
    )
    for edge in commit_history.get("edges", []):
        date_str = edge["node"]["committedDate"]
        commits.append(
            {
                "date": date_str,
                "parsed_date": parse_github_datetime(date_str),
                "author": (
                    (edge["node"].get("author") or {})
                    .get("user") or {}
                ).get("login", "unknown"),
            }
        )

    # Calculate derived metrics using pre-parsed dates
    now = datetime.utcnow()
    seven_days_ago = now - timedelta(days=7)
    thirty_days_ago = now - timedelta(days=30)
    ninety_days_ago = now - timedelta(days=90)

    # Count commits in each time window (single pass through data)
    commits_7d = sum(1 for c in commits if c["parsed_date"] > seven_days_ago)
    commits_30d = sum(1 for c in commits if c["parsed_date"] > thirty_days_ago)
    commits_90d = sum(1 for c in commits if c["parsed_date"] > ninety_days_ago)

    # Count unique authors in each time window
    unique_authors_7d = len(
        set(c["author"] for c in commits if c["parsed_date"] > seven_days_ago)
    )
    unique_authors_30d = len(
        set(c["author"] for c in commits if c["parsed_date"] > thirty_days_ago)
    )

    # Calculate repository age in days (handle brand new repos)
    created_at = parse_github_datetime(repo_data["createdAt"])
    repo_age_days = max(
        (now - created_at).days, 1
    )  # Minimum 1 day to avoid division issues

    # Stars per month (normalized, use 0.1 month minimum for very new repos)
    repo_age_months = max(repo_age_days / 30.0, 0.1)
    stars_per_month = repo_data["stargazerCount"] / repo_age_months

    metrics = {
        "repo": f"{owner}/{repo}",
        "description": repo_data.get("description", ""),
        "license": repo_data.get("licenseInfo", {}).get("name", "Unknown"),
        "created_at": repo_data["createdAt"],
        "updated_at": repo_data["updatedAt"],
        "metrics": {
            "stars": repo_data["stargazerCount"],
            "forks": repo_data["forkCount"],
            "open_issues": repo_data["issues"]["totalCount"],
            "closed_issues": repo_data["closedIssues"]["totalCount"],
            "open_prs": repo_data["pullRequests"]["totalCount"],
            "merged_prs": repo_data["mergedPRs"]["totalCount"],
            "contributors": repo_data["mentionableUsers"]["totalCount"],
        },
        "derived": {
            "repo_age_days": repo_age_days,
            "stars_per_month": round(stars_per_month, 2),
            "commits_7d": commits_7d,
            "commits_30d": commits_30d,
            "commits_90d": commits_90d,
            "unique_authors_7d": unique_authors_7d,
            "unique_authors_30d": unique_authors_30d,
            "issue_close_rate": round(
                repo_data["closedIssues"]["totalCount"]
                / max(
                    repo_data["closedIssues"]["totalCount"]
                    + repo_data["issues"]["totalCount"],
                    1,
                )
                * 100,
                2,
            ),
            "pr_merge_rate": round(
                repo_data["mergedPRs"]["totalCount"]
                / max(
                    repo_data["mergedPRs"]["totalCount"]
                    + repo_data["pullRequests"]["totalCount"],
                    1,
                )
                * 100,
                2,
            ),
        },
        "recent_releases": [
            {"tag": r["tagName"], "date": r["publishedAt"]}
            for r in repo_data.get("releases", {}).get("nodes", [])
        ],
    }

    # Cache the results for future use (cache_hours sets the Redis TTL)
    store_github_metrics_cache(repo_full, metrics["metrics"], metrics["derived"], ttl_hours=cache_hours)

    # Store time-series data for historical tracking
    store_timeseries_snapshot(repo_full, metrics["metrics"], metrics["derived"])

    # Store commit history for detailed timeline analysis
    store_commit_history(repo_full, commits)

    logger.info(f"Successfully fetched metrics for {repo_full}")
    metrics["cached"] = False
    return metrics


@tool
def fetch_recent_issues(owner: str, repo: str, count: int = 20, cache_hours: int = 8) -> list:
    """
    Fetch recent issues for sentiment analysis.
    Results are cached for 8 hours to reduce GitHub API usage.

    Args:
        owner: Repository owner
        repo: Repository name
        count: Number of issues to fetch (default 20, max 100)
        cache_hours: Use cached results if less than this many hours old (default 8)

    Returns:
        List of issues with title, body, labels, state, and timestamps
    """
    repo_full = f"{owner}/{repo}"

    # Check cache first
    cached = get_cached_github_data(repo_full, "issues")
    if cached is not None:
        logger.info(f"Using cached issues for {repo_full} ({len(cached)} items)")
        return {"issues": cached, "count": len(cached), "cached": True}

    logger.info(f"Fetching {count} recent issues for {repo_full}")

    query = """
    query($owner: String!, $repo: String!, $count: Int!) {
      repository(owner: $owner, name: $repo) {
        issues(first: $count, orderBy: {field: CREATED_AT, direction: DESC}) {
          nodes {
            title
            body
            state
            createdAt
            closedAt
            author { login }
            labels(first: 5) { nodes { name } }
            comments { totalCount }
            reactions { totalCount }
          }
        }
      }
    }
    """

    try:
        result = _execute_graphql(
            query, {"owner": owner, "repo": repo, "count": min(count, 100)}
        )
    except RepositoryNotFoundError as e:
        logger.warning(f"Repository {repo_full} not found when fetching issues: {e}")
        return {"issues": [], "count": 0, "cached": False, "error": str(e)}

    issues_data = (
        result.get("data", {}).get("repository", {}).get("issues", {}).get("nodes", [])
    )

    issues = []
    for issue in issues_data:
        # Calculate time to close if closed
        time_to_close = None
        if issue.get("closedAt"):
            created = parse_github_datetime(issue["createdAt"])
            closed = parse_github_datetime(issue["closedAt"])
            time_to_close = (closed - created).days

        issues.append(
            {
                "title": issue["title"],
                "body": issue.get("body", "")[:500],  # Truncate for context
                "state": issue["state"],
                "created_at": issue["createdAt"],
                "closed_at": issue.get("closedAt"),
                "time_to_close_days": time_to_close,
                "author": (issue.get("author") or {}).get("login", "unknown"),
                "labels": [l["name"] for l in issue.get("labels", {}).get("nodes", [])],
                "comment_count": issue["comments"]["totalCount"],
                "reaction_count": issue["reactions"]["totalCount"],
            }
        )

    logger.info(f"Fetched {len(issues)} issues for {repo_full}")
    store_github_data_cache(repo_full, "issues", issues, ttl_hours=cache_hours)
    return {"issues": issues, "count": len(issues), "cached": False}


@tool
def fetch_repo_discussions(owner: str, repo: str, count: int = 10, cache_hours: int = 8) -> list:
    """
    Fetch recent GitHub Discussions for community sentiment analysis.
    Results are cached for 8 hours to reduce GitHub API usage.

    Args:
        owner: Repository owner
        repo: Repository name
        count: Number of discussions to fetch
        cache_hours: Use cached results if less than this many hours old (default 8)

    Returns:
        List of discussions with title, body, category, and engagement metrics
    """
    repo_full = f"{owner}/{repo}"

    # Check cache first
    cached = get_cached_github_data(repo_full, "discussions")
    if cached is not None:
        logger.info(f"Using cached discussions for {repo_full} ({len(cached)} items)")
        return {"discussions": cached, "count": len(cached), "cached": True}

    logger.info(f"Fetching {count} discussions for {repo_full}")

    query = """
    query($owner: String!, $repo: String!, $count: Int!) {
      repository(owner: $owner, name: $repo) {
        discussions(first: $count, orderBy: {field: CREATED_AT, direction: DESC}) {
          nodes {
            title
            body
            category { name }
            createdAt
            author { login }
            comments { totalCount }
            upvoteCount
            answerChosenAt
          }
        }
      }
    }
    """

    try:
        result = _execute_graphql(
            query, {"owner": owner, "repo": repo, "count": min(count, 50)}
        )
        discussions = (
            result.get("data", {})
            .get("repository", {})
            .get("discussions", {})
            .get("nodes", [])
        )

        formatted_discussions = [
            {
                "title": d["title"],
                "body": d.get("body", "")[:500],
                "category": d.get("category", {}).get("name", "Unknown"),
                "created_at": d["createdAt"],
                "author": (d.get("author") or {}).get("login", "unknown"),
                "comment_count": d["comments"]["totalCount"],
                "upvotes": d["upvoteCount"],
                "has_answer": d.get("answerChosenAt") is not None,
            }
            for d in discussions
        ]

        logger.info(f"Fetched {len(formatted_discussions)} discussions for {repo_full}")
        store_github_data_cache(repo_full, "discussions", formatted_discussions, ttl_hours=cache_hours)
        return {"discussions": formatted_discussions, "count": len(formatted_discussions), "cached": False}
    except RepositoryNotFoundError as e:
        logger.warning(f"Repository {repo_full} not found when fetching discussions: {e}")
        return {"discussions": [], "count": 0, "cached": False, "error": str(e)}
    except GitHubAPIError as e:
        # Discussions might not be enabled for repo
        logger.warning(f"Could not fetch discussions for {repo_full}: {e}")
        return {"discussions": [], "count": 0, "cached": False}


@tool
def fetch_repo_info_from_web(owner: str, repo: str) -> dict:
    """
    Fetch GitHub repository information from the public web using web search.

    This is a fallback when the GitHub API is inaccessible (e.g., SAML enforcement).
    Uses Tavily to search for publicly available repository information.

    Args:
        owner: Repository owner (e.g., "elastic")
        repo: Repository name (e.g., "elasticsearch")

    Returns:
        Dictionary with repository information gathered from web sources
    """
    repo_full = f"{owner}/{repo}"
    github_url = f"https://github.com/{repo_full}"

    logger.info(f"Fetching repo info from web for {repo_full} (API fallback)")

    # Single composite query instead of 3 separate calls
    composite_query = (
        f"{owner}/{repo} GitHub repository stars forks contributors commits open source"
    )
    results = {
        "repo": repo_full,
        "github_url": github_url,
        "source": "web_fallback",
        "note": "Data gathered from web sources due to GitHub API access restrictions",
        "metrics_approximate": True,
        "web_findings": [],
    }

    try:
        search_results = tavily_search.invoke({"query": composite_query, "max_results": 8})
        if search_results and "results" in search_results:
            results["web_findings"].extend(search_results["results"])
    except Exception as e:
        logger.warning(f"Web search fallback failed for '{repo_full}': {e}")

    # Parse numbers from web findings if possible
    import re

    all_text = " ".join([r.get("content", "") for r in results["web_findings"]])

    # Try to extract star count
    star_match = re.search(
        r"(\d{1,3}(?:,\d{3})*|\d+\.?\d*[kK])\s*(?:stars?|⭐)", all_text, re.IGNORECASE
    )
    if star_match:
        stars_str = star_match.group(1).replace(",", "")
        if "k" in stars_str.lower():
            results["estimated_stars"] = int(
                float(stars_str.lower().replace("k", "")) * 1000
            )
        else:
            results["estimated_stars"] = int(stars_str)

    # Try to extract fork count
    fork_match = re.search(
        r"(\d{1,3}(?:,\d{3})*|\d+\.?\d*[kK])\s*forks?", all_text, re.IGNORECASE
    )
    if fork_match:
        forks_str = fork_match.group(1).replace(",", "")
        if "k" in forks_str.lower():
            results["estimated_forks"] = int(
                float(forks_str.lower().replace("k", "")) * 1000
            )
        else:
            results["estimated_forks"] = int(forks_str)

    logger.info(
        f"Gathered web info for {repo_full}: {len(results['web_findings'])} sources"
    )
    return results
