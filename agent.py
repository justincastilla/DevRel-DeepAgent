"""
Main DevRel Research Agent - Orchestrator for multi-agent research system.
"""

import threading
from typing import Optional

from dotenv import load_dotenv

from config import config
from utils.logging_utils import setup_logging, get_logger
from exceptions import ConfigurationError

# Setup logging
setup_logging()
logger = get_logger(__name__)

# Load environment variables
load_dotenv()

# =============================================================================
# Lazy Agent Initialization (Singleton Pattern)
# =============================================================================

_agent = None
_agent_lock = threading.Lock()
_config_validated = False
_current_model = None

# Model configurations
MODELS = {
    "claude": "anthropic:claude-sonnet-4-5-20250929",
    "gpt": "openai:gpt-5",
}
DEFAULT_MODEL = "claude"


def _validate_config() -> None:
    """
    Validate configuration on first access.
    Raises ConfigurationError if required variables are missing.
    """
    global _config_validated

    if _config_validated:
        return

    missing_vars = config.validate()
    if missing_vars:
        error_msg = f"Missing required environment variables: {', '.join(missing_vars)}"
        logger.error(error_msg)
        raise ConfigurationError(error_msg)

    logger.info("Configuration validated successfully")
    logger.debug(f"Config summary: {config.get_config_summary()}")
    _config_validated = True


def get_agent(model: str = None):
    """
    Get the singleton DevRel Research Agent instance.

    Uses lazy initialization to avoid import-time side effects.
    Thread-safe via double-checked locking pattern.

    Args:
        model: Model to use - "claude" or "gpt" (default: "claude")
               If agent already exists with different model, it will be recreated.

    Returns:
        The configured agent instance

    Raises:
        ConfigurationError: If required environment variables are missing
    """
    global _agent, _current_model

    # Resolve model name to full model string
    model_key = model or DEFAULT_MODEL
    if model_key not in MODELS:
        raise ValueError(
            f"Unknown model '{model_key}'. Choose from: {list(MODELS.keys())}"
        )
    model_string = MODELS[model_key]

    # Fast path: agent already created with same model
    if _agent is not None and _current_model == model_key:
        return _agent

    # Slow path: need to create agent (thread-safe)
    with _agent_lock:
        # Double-check after acquiring lock
        if _agent is not None and _current_model == model_key:
            return _agent

        # Validate configuration before creating agent
        _validate_config()

        # Import dependencies only when needed (reduces import-time overhead)
        from deepagents import create_deep_agent
        from prompts import get_system_prompt
        from subagents import (
            metrics_subagent,
            sentiment_subagent,
            web_subagent,
            elastic_subagent,
        )
        from tools import (
            find_similar_technologies,
            compare_technologies,
            get_trend_data,
            search_by_tags,
            calculate_viability_score,
            store_research_report,
        )

        # Build system prompt with configuration
        system_prompt = get_system_prompt(
            max_concurrent=config.MAX_CONCURRENT_SUBAGENTS,
            max_iterations=config.MAX_ITERATIONS_PER_SUBAGENT,
        )

        logger.info(
            f"Creating DevRel Research Agent with model: {model_key} ({model_string})"
        )

        # Create the main orchestrator agent
        _agent = create_deep_agent(
            model=model_string,
            system_prompt=system_prompt,
            tools=[
                # Elasticsearch tools for the orchestrator
                find_similar_technologies,
                compare_technologies,
                get_trend_data,
                search_by_tags,
                # Scoring tool
                calculate_viability_score,
                # Storage tool - save final reports
                store_research_report,
            ],
            subagents=[
                metrics_subagent,
                sentiment_subagent,
                web_subagent,
                elastic_subagent,
            ],
        )

        _current_model = model_key
        logger.info("DevRel Research Agent created successfully")
        return _agent


def reset_agent() -> None:
    """
    Reset the agent singleton (primarily for testing).
    Forces re-creation on next get_agent() call.
    """
    global _agent, _config_validated, _current_model

    with _agent_lock:
        _agent = None
        _config_validated = False
        _current_model = None
        logger.debug("Agent singleton reset")


# For direct invocation
if __name__ == "__main__":
    import sys

    # Example usage
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = (
            "Evaluate langchain-ai/deepagents for building DevRel research automation"
        )

    logger.info(f"Running query: {query}")
    print(f"\n{'='*80}")
    print(f"Query: {query}")
    print(f"{'='*80}\n")

    result = get_agent().invoke({"messages": [{"role": "user", "content": query}]})

    print("\n" + "=" * 80)
    print("RESULT:")
    print("=" * 80)
    print(result["messages"][-1].content)
    print("=" * 80 + "\n")

    logger.info("Query completed successfully")
