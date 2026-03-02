"""
Test suite for Elastic Agent ES|QL tools.

Tests the remote ES|QL tools created in the Elastic serverless instance
via the Kibana Agent Builder API.

Usage:
    python scripts/test_elastic_agent_tools.py
    python scripts/test_elastic_agent_tools.py --tool find-similar-technologies
    python scripts/test_elastic_agent_tools.py --list
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables
load_dotenv()


@dataclass
class ToolTestCase:
    """Represents a test case for an ES|QL tool."""
    tool_id: str
    description: str
    params: dict
    expected_fields: list[str]  # Fields expected in successful response


class ElasticAgentToolTester:
    """Test harness for Elastic Agent ES|QL tools."""

    def __init__(self):
        self.kibana_url = os.getenv("KIBANA_URL") or os.getenv("ELASTICSEARCH_HOST", "").replace(":9243", ":5601")
        self.api_key = os.getenv("KIBANA_API_KEY") or os.getenv("ELASTICSEARCH_API_KEY")

        if not self.kibana_url or not self.api_key:
            raise ValueError(
                "Missing required environment variables: KIBANA_URL and KIBANA_API_KEY "
                "(or ELASTICSEARCH_HOST and ELASTICSEARCH_API_KEY)"
            )

        # Ensure URL doesn't have trailing slash
        self.kibana_url = self.kibana_url.rstrip("/")

        self.headers = {
            "kbn-xsrf": "true",
            "Authorization": f"ApiKey {self.api_key}",
            "Content-Type": "application/json",
        }

        # Test data - use realistic sample values
        self.sample_repo = "langchain-ai/langgraph"
        self.sample_start_date = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT00:00:00Z")
        self.sample_min_timestamp = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00Z")

        # Define all test cases
        self.test_cases = self._build_test_cases()

    def _build_test_cases(self) -> list[ToolTestCase]:
        """Build test cases for all 14 ES|QL tools."""
        return [
            ToolTestCase(
                tool_id="find-similar-technologies",
                description="Semantic search for similar technologies",
                params={
                    "description": "AI agent frameworks for Python",
                    "limit": 5,
                },
                expected_fields=["repo", "timestamp"],
            ),
            ToolTestCase(
                tool_id="get-trend-data",
                description="Historical trend analysis for a repository",
                params={
                    "repo_name": self.sample_repo,
                    "start_date": self.sample_start_date,
                },
                expected_fields=["repo", "timestamp"],
            ),
            ToolTestCase(
                tool_id="get-latest-snapshot",
                description="Most recent snapshot for comparison",
                params={
                    "repo_name": self.sample_repo,
                },
                expected_fields=["repo", "timestamp"],
            ),
            ToolTestCase(
                tool_id="search-by-tags",
                description="Search technologies by tags",
                params={
                    "tag_pattern": "*python*",
                    "min_viability": 0,
                },
                expected_fields=["repo"],
            ),
            ToolTestCase(
                tool_id="get-cached-search",
                description="Check cached web search results",
                params={
                    "query_hash": "test_hash_12345",
                    "min_timestamp": self.sample_min_timestamp,
                },
                expected_fields=[],  # May return empty if no cache
            ),
            ToolTestCase(
                tool_id="get-cached-github-metrics",
                description="Check cached GitHub metrics",
                params={
                    "repo_name": self.sample_repo,
                    "min_timestamp": self.sample_min_timestamp,
                },
                expected_fields=[],  # May return empty if no cache
            ),
            ToolTestCase(
                tool_id="get-repo-timeseries",
                description="Time-series metrics for visualization",
                params={
                    "repo_name": self.sample_repo,
                    "start_date": self.sample_start_date,
                },
                expected_fields=["repo", "timestamp"],
            ),
            ToolTestCase(
                tool_id="get-repo-timeseries-stats",
                description="Aggregated time-series statistics",
                params={
                    "repo_name": self.sample_repo,
                    "start_date": self.sample_start_date,
                },
                expected_fields=["repo"],
            ),
            ToolTestCase(
                tool_id="get-adoption-signals",
                description="Adoption signals (blog posts, case studies)",
                params={
                    "repo_name": self.sample_repo,
                    "start_date": self.sample_start_date,
                },
                expected_fields=[],  # May return empty
            ),
            ToolTestCase(
                tool_id="get-adoption-signals-by-type",
                description="Adoption signals filtered by type",
                params={
                    "repo_name": self.sample_repo,
                    "signal_type": "blog_post",
                    "start_date": self.sample_start_date,
                },
                expected_fields=[],  # May return empty
            ),
            ToolTestCase(
                tool_id="count-adoption-signals",
                description="Count adoption signals by type",
                params={
                    "repo_name": self.sample_repo,
                    "start_date": self.sample_start_date,
                },
                expected_fields=[],  # May return empty
            ),
            ToolTestCase(
                tool_id="get-latest-report",
                description="Most recent research report",
                params={
                    "repo_name": self.sample_repo,
                },
                expected_fields=[],  # May return empty if no reports
            ),
            ToolTestCase(
                tool_id="get-cached-report",
                description="Cached research report within age limit",
                params={
                    "repo_name": self.sample_repo,
                    "min_timestamp": self.sample_min_timestamp,
                },
                expected_fields=[],  # May return empty
            ),
            ToolTestCase(
                tool_id="get-past-discoveries",
                description="Past technology discovery results",
                params={
                    "start_date": self.sample_start_date,
                },
                expected_fields=[],  # May return empty
            ),
            ToolTestCase(
                tool_id="search-discoveries-by-use-case",
                description="Search discoveries by use case",
                params={
                    "use_case_pattern": "*agent*",
                    "start_date": self.sample_start_date,
                },
                expected_fields=[],  # May return empty
            ),
            ToolTestCase(
                tool_id="get-all-discovered-repos",
                description="All discovered repositories",
                params={},
                expected_fields=[],  # May return empty
            ),
        ]

    def _invoke_tool(self, tool_id: str, params: dict) -> dict:
        """
        Invoke an ES|QL tool via the Kibana Agent Builder API.

        Args:
            tool_id: The tool identifier
            params: Parameters to pass to the tool

        Returns:
            Response data from the tool
        """
        # The execute endpoint for agent tools
        url = f"{self.kibana_url}/api/agent_builder/tools/_execute"

        payload = {
            "tool_id": tool_id,
            "tool_params": params,
        }

        response = httpx.post(
            url,
            headers=self.headers,
            json=payload,
            timeout=30.0,
        )

        return {
            "status_code": response.status_code,
            "data": response.json() if response.content else {},
            "success": response.status_code == 200,
        }

    def _check_tool_exists(self, tool_id: str) -> bool:
        """Check if a tool exists in the agent builder."""
        # List all tools and check if the tool_id exists
        tools = self.list_tools()
        return any(t.get("id") == tool_id for t in tools)

    def list_tools(self) -> list[dict]:
        """List all available tools."""
        url = f"{self.kibana_url}/api/agent_builder/tools"

        try:
            response = httpx.get(url, headers=self.headers, timeout=10.0)
            if response.status_code == 200:
                tools = response.json()
                # Handle various response formats
                if isinstance(tools, list):
                    return tools
                elif isinstance(tools, dict) and "results" in tools:
                    return tools["results"]
                elif isinstance(tools, dict) and "tools" in tools:
                    return tools["tools"]
                elif isinstance(tools, dict):
                    return [tools]
        except httpx.RequestError as e:
            print(f"Error listing tools: {e}")

        return []

    def get_tool_ids(self) -> list[str]:
        """Get list of tool IDs."""
        tools = self.list_tools()
        return [t.get("id", "unknown") for t in tools if isinstance(t, dict)]

    def run_test(self, test_case: ToolTestCase) -> dict:
        """
        Run a single test case.

        Args:
            test_case: The test case to run

        Returns:
            Test result dictionary
        """
        result = {
            "tool_id": test_case.tool_id,
            "description": test_case.description,
            "params": test_case.params,
            "success": False,
            "error": None,
            "response": None,
            "execution_time_ms": 0,
        }

        # Check if tool exists first
        if not self._check_tool_exists(test_case.tool_id):
            result["error"] = f"Tool '{test_case.tool_id}' not found. Create it first using the Dev Tools commands."
            return result

        # Time the execution
        import time
        start = time.time()

        try:
            response = self._invoke_tool(test_case.tool_id, test_case.params)
            result["execution_time_ms"] = int((time.time() - start) * 1000)
            result["response"] = response

            if response["success"]:
                result["success"] = True

                # Check for errors in the response
                data = response.get("data", {})
                results_list = data.get("results", [])

                # Check if any result is an error
                for res_item in results_list:
                    if res_item.get("type") == "error":
                        error_msg = res_item.get("data", {}).get("message", "Unknown error")
                        result["error"] = f"Tool error: {error_msg[:100]}"
                        result["success"] = False
                        break

                # Validate expected fields in tabular_data results
                if result["success"] and test_case.expected_fields:
                    for res_item in results_list:
                        if res_item.get("type") == "tabular_data":
                            tabular = res_item.get("data", {})
                            columns = [col.get("name") for col in tabular.get("columns", [])]
                            values = tabular.get("values", [])

                            # Check if expected fields are in columns
                            missing_fields = [f for f in test_case.expected_fields if f not in columns]
                            if missing_fields:
                                result["error"] = f"Missing expected fields: {missing_fields}"
                                result["success"] = False
                            elif not values:
                                # No data but query succeeded - that's ok for cache checks
                                pass
                            break
            else:
                result["error"] = f"HTTP {response['status_code']}: {response.get('data', {})}"

        except httpx.RequestError as e:
            result["execution_time_ms"] = int((time.time() - start) * 1000)
            result["error"] = f"Request failed: {str(e)}"
        except Exception as e:
            result["execution_time_ms"] = int((time.time() - start) * 1000)
            result["error"] = f"Unexpected error: {str(e)}"

        return result

    def run_all_tests(self, tool_filter: Optional[str] = None) -> list[dict]:
        """
        Run all test cases or a filtered subset.

        Args:
            tool_filter: Optional tool ID to filter tests

        Returns:
            List of test results
        """
        results = []

        test_cases = self.test_cases
        if tool_filter:
            test_cases = [tc for tc in test_cases if tc.tool_id == tool_filter]
            if not test_cases:
                print(f"No test case found for tool: {tool_filter}")
                return results

        total = len(test_cases)

        print(f"\n{'='*80}")
        print("ELASTIC AGENT ES|QL TOOLS - TEST SUITE")
        print(f"{'='*80}")
        print(f"Kibana URL: {self.kibana_url}")
        print(f"Running {total} test(s)...")
        print(f"{'='*80}\n")

        for i, test_case in enumerate(test_cases, 1):
            print(f"[{i}/{total}] Testing: {test_case.tool_id}")
            print(f"         {test_case.description}")

            result = self.run_test(test_case)
            results.append(result)

            if result["success"]:
                print(f"         ✓ PASSED ({result['execution_time_ms']}ms)")
            else:
                print(f"         ✗ FAILED: {result['error']}")

            print()

        # Summary
        passed = sum(1 for r in results if r["success"])
        failed = total - passed

        print(f"{'='*80}")
        print(f"SUMMARY: {passed}/{total} passed, {failed} failed")
        print(f"{'='*80}\n")

        return results


def main():
    """Main entry point for the test suite."""
    parser = argparse.ArgumentParser(
        description="Test Elastic Agent ES|QL tools"
    )
    parser.add_argument(
        "--tool",
        type=str,
        help="Run tests for a specific tool ID only",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available tools in the agent builder",
    )
    parser.add_argument(
        "--list-tests",
        action="store_true",
        help="List all test cases defined in this suite",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )

    args = parser.parse_args()

    try:
        tester = ElasticAgentToolTester()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    if args.list:
        print("\nAvailable tools in Agent Builder:")
        tool_ids = tester.get_tool_ids()
        if tool_ids:
            for tool_id in tool_ids:
                print(f"  - {tool_id}")
        else:
            print("  (No tools found or unable to list)")
        print()
        return

    if args.list_tests:
        print("\nTest cases defined in this suite:")
        for tc in tester.test_cases:
            print(f"  - {tc.tool_id}: {tc.description}")
        print()
        return

    # Run tests
    results = tester.run_all_tests(tool_filter=args.tool)

    if args.json:
        # Clean up results for JSON output (remove non-serializable items)
        clean_results = []
        for r in results:
            clean_r = {k: v for k, v in r.items() if k != "response"}
            clean_r["response_status"] = r.get("response", {}).get("status_code")
            clean_results.append(clean_r)
        print(json.dumps(clean_results, indent=2))

    # Exit with error code if any tests failed
    if any(not r["success"] for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
