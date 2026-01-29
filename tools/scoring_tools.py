"""
Viability scoring tools for technology assessment.
"""

from langchain_core.tools import tool

from exceptions import ScoringError
from utils.logging_utils import get_logger

logger = get_logger(__name__)


def _to_number(value, default=0):
    """Safely convert a value to a number."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        # Handle common string formats
        value = value.strip().replace(",", "").replace("%", "")
        if not value or value.lower() in ("n/a", "unknown", "none", "null"):
            return default
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _to_sentiment(value, default=0.5):
    """Convert sentiment value (string or number) to float 0-1."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        value_lower = value.lower().strip()
        # Handle descriptive sentiment strings
        sentiment_map = {
            "very positive": 0.9,
            "positive": 0.75,
            "mostly positive": 0.7,
            "somewhat positive": 0.6,
            "neutral": 0.5,
            "mixed": 0.5,
            "somewhat negative": 0.4,
            "mostly negative": 0.3,
            "negative": 0.25,
            "very negative": 0.1,
        }
        if value_lower in sentiment_map:
            return sentiment_map[value_lower]
        # Try parsing as number
        try:
            return float(value.replace("%", "")) / 100 if "%" in value else float(value)
        except ValueError:
            return default
    return default


@tool
def calculate_viability_score(
    metrics: dict,
    sentiment: dict,
    adoption: dict,
) -> dict:
    """
    Calculate a weighted viability score for a technology.

    Scoring breakdown:
    - Health (40%): Stars, commits, contributor activity, issue close rate
    - Community (30%): Sentiment, maintainer engagement, response times
    - Adoption (30%): Blog posts, case studies, job postings, conference talks

    Args:
        metrics: GitHub metrics from fetch_repo_metrics
        sentiment: Sentiment analysis from sentiment-agent
        adoption: Adoption signals from web-research-agent

    Returns:
        Score (0-100) with detailed breakdown and risk flags
    """
    logger.info(f"Calculating viability score for repository")
    logger.debug(f"Input metrics: {metrics}")
    logger.debug(f"Input sentiment: {sentiment}")
    logger.debug(f"Input adoption: {adoption}")

    try:
        risk_flags = []

        # Handle case where metrics might be nested or flat
        metrics_data = metrics.get("metrics", metrics) if isinstance(metrics, dict) else {}
        derived_data = metrics.get("derived", {}) if isinstance(metrics, dict) else {}

        logger.debug(f"Parsed metrics_data: {metrics_data}")
        logger.debug(f"Parsed derived_data: {derived_data}")

        # === HEALTH SCORE (40%) ===
        health_score = 0

        # Stars (max 15 points)
        stars = _to_number(metrics_data.get("stars", 0))
        if stars >= 10000:
            health_score += 15
        elif stars >= 5000:
            health_score += 12
        elif stars >= 1000:
            health_score += 8
        elif stars >= 100:
            health_score += 4
        else:
            risk_flags.append("low_stars")

        # Commit activity - last 30 days (max 15 points)
        commits_30d = _to_number(derived_data.get("commits_30d", 0))
        if commits_30d >= 50:
            health_score += 15
        elif commits_30d >= 20:
            health_score += 12
        elif commits_30d >= 5:
            health_score += 8
        elif commits_30d >= 1:
            health_score += 4
        else:
            risk_flags.append("low_recent_commits")

        # Contributors (max 10 points)
        contributors = _to_number(metrics_data.get("contributors", 0))
        if contributors >= 50:
            health_score += 10
        elif contributors >= 20:
            health_score += 8
        elif contributors >= 5:
            health_score += 5
        elif contributors >= 2:
            health_score += 2
        else:
            risk_flags.append("single_maintainer")

        # === COMMUNITY SCORE (30%) ===
        community_score = 0

        # Sentiment (max 15 points)
        sentiment_value = _to_sentiment(sentiment.get("overall_sentiment", 0.5))
        if sentiment_value >= 0.8:
            community_score += 15
        elif sentiment_value >= 0.6:
            community_score += 12
        elif sentiment_value >= 0.4:
            community_score += 8
        elif sentiment_value >= 0.2:
            community_score += 4
        else:
            risk_flags.append("negative_sentiment")

        # Issue close rate (max 10 points)
        close_rate = _to_number(derived_data.get("issue_close_rate", 0))
        if close_rate >= 80:
            community_score += 10
        elif close_rate >= 60:
            community_score += 8
        elif close_rate >= 40:
            community_score += 5
        else:
            risk_flags.append("low_issue_close_rate")

        # Maintainer response assessment (max 5 points)
        responsiveness = sentiment.get("maintainer_responsiveness", "unknown")
        if responsiveness == "excellent":
            community_score += 5
        elif responsiveness == "good":
            community_score += 3
        elif responsiveness == "fair":
            community_score += 1

        # Red flags from sentiment analysis (deductions)
        red_flags = sentiment.get("red_flags", [])
        if "abandoned" in red_flags:
            community_score -= 5
            risk_flags.append("abandonment_concerns")
        if "breaking_changes" in red_flags:
            community_score -= 3
            risk_flags.append("breaking_change_concerns")
        if "maintainer_unresponsive" in red_flags:
            community_score -= 5
            risk_flags.append("maintainer_unresponsive")

        community_score = max(0, community_score)  # Floor at 0

        # === ADOPTION SCORE (30%) ===
        adoption_score = 0

        # Blog posts and tutorials (max 10 points)
        blog_count = _to_number(adoption.get("blog_posts", 0))
        if blog_count >= 20:
            adoption_score += 10
        elif blog_count >= 10:
            adoption_score += 8
        elif blog_count >= 5:
            adoption_score += 5
        elif blog_count >= 1:
            adoption_score += 2
        else:
            risk_flags.append("low_content_coverage")

        # Production case studies (max 10 points)
        case_studies = _to_number(adoption.get("case_studies", 0))
        if case_studies >= 5:
            adoption_score += 10
        elif case_studies >= 3:
            adoption_score += 8
        elif case_studies >= 1:
            adoption_score += 5
        else:
            risk_flags.append("no_production_case_studies")

        # Job postings mentioning tech (max 5 points)
        job_mentions = _to_number(adoption.get("job_postings", 0))
        if job_mentions >= 50:
            adoption_score += 5
        elif job_mentions >= 20:
            adoption_score += 4
        elif job_mentions >= 5:
            adoption_score += 2

        # Conference talks (max 5 points)
        talks = _to_number(adoption.get("conference_talks", 0))
        if talks >= 5:
            adoption_score += 5
        elif talks >= 2:
            adoption_score += 3
        elif talks >= 1:
            adoption_score += 1

        # === FINAL CALCULATION ===
        total_score = health_score + community_score + adoption_score

        # Determine recommendation
        if total_score >= 80:
            recommendation = "STRONG_COVER"
            recommendation_text = "Highly recommended for coverage. Strong signals across all dimensions."
        elif total_score >= 60:
            recommendation = "COVER"
            recommendation_text = "Recommended for coverage with noted caveats."
        elif total_score >= 40:
            recommendation = "WATCH"
            recommendation_text = "Monitor for improvements. Not ready for primary coverage yet."
        else:
            recommendation = "SKIP"
            recommendation_text = "Not recommended for coverage at this time."

        result = {
            "viability_score": total_score,
            "breakdown": {
                "health": {"score": health_score, "max": 40},
                "community": {"score": community_score, "max": 30},
                "adoption": {"score": adoption_score, "max": 30},
            },
            "risk_flags": list(set(risk_flags)),  # Remove duplicates
            "recommendation": recommendation,
            "recommendation_text": recommendation_text,
        }

        logger.info(f"Calculated viability score: {total_score}/100 - {recommendation}")
        return result

    except Exception as e:
        logger.error(f"Failed to calculate viability score: {e}")
        raise ScoringError(f"Failed to calculate viability score: {e}") from e
