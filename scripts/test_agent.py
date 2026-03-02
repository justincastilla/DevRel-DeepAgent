"""
Test script for the DevRel Research Agent.
Run various queries to verify functionality.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
from agent import agent
from utils.logging_utils import setup_logging, get_logger

# Setup logging
setup_logging()
logger = get_logger(__name__)

TEST_QUERIES = [
    # Single technology evaluation
    "Evaluate langchain-ai/deepagents for building research automation tools",

    # Comparison request
    "Compare langchain-ai/langgraph vs crewAIInc/crewAI for multi-agent orchestration",

    # Discovery request
    "Find the best AI agent frameworks for Python released in the last year",

    # Specific concern investigation
    "Is there any evidence of maintainer burnout or project abandonment for facebook/react?",
]


async def run_test(query: str):
    """Run a single test query."""
    print(f"\n{'='*80}")
    print(f"QUERY: {query}")
    print(f"{'='*80}\n")
    logger.info(f"Running test query: {query}")

    try:
        result = await agent.ainvoke({
            "messages": [{"role": "user", "content": query}]
        })

        print("\nRESPONSE:")
        print(f"{'='*80}")
        print(result["messages"][-1].content)
        print(f"{'='*80}\n")

        logger.info("Test query completed successfully")
    except Exception as e:
        logger.error(f"Test query failed: {e}")
        print(f"\nERROR: {e}\n")


async def main():
    """Run all test queries."""
    print("\n" + "="*80)
    print("DEVREL RESEARCH AGENT - TEST SUITE")
    print("="*80)

    for i, query in enumerate(TEST_QUERIES, 1):
        print(f"\n[Test {i}/{len(TEST_QUERIES)}]")
        await run_test(query)

        # Pause between queries to avoid rate limits
        if i < len(TEST_QUERIES):
            print("Waiting 5 seconds before next test...")
            await asyncio.sleep(5)

    print("\n" + "="*80)
    print("TEST SUITE COMPLETED")
    print("="*80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
