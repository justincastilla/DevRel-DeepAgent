# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DevRel Research Agent is a multi-agent system built on LangChain's DeepAgents framework. It helps Developer Advocates evaluate technologies by analyzing GitHub health metrics, community sentiment, and real-world adoption signals, then stores results in Elasticsearch for historical tracking.

## Common Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Setup Elasticsearch indices (required before first use)
python scripts/setup_elasticsearch.py

# Natural language queries (LLM finds and analyzes repos automatically)
python cli.py ask "What are the best Python web frameworks and how do they compare?"
python cli.py ask "Evaluate the top 3 LLM orchestration libraries"
python cli.py ask "Compare MongoDB vs PostgreSQL for real-time analytics"

# Discover new technologies for a use case
python cli.py discover "UI frameworks for multi-modal AI chat"
python cli.py discover "real-time collaboration libraries" --limit 5

# Evaluate a specific repository
python cli.py evaluate langchain-ai/deepagents
python cli.py evaluate langchain-ai/deepagents --use-case "building research agents"

# Compare multiple repositories
python cli.py compare crewAIInc/crewAI microsoft/autogen --use-case "multi-agent orchestration"

# Search previously researched technologies (in Elasticsearch)
python cli.py search "AI agent frameworks" --tags ai-agents python

# Export results to file
python cli.py evaluate langchain-ai/deepagents --output report.md --format markdown

# Verbose mode - see real-time agent activity
python cli.py ask "Compare MongoDB and Elasticsearch" --verbose
python cli.py compare mongodb/mongo elastic/elasticsearch -v

# Run test suite
python scripts/test_agent.py

# Test the elastic-agent's direct-Elasticsearch tools
python scripts/test_elastic_subagent_tools.py

# (Legacy/dormant) Test the Elastic Agent Builder ES|QL tools via /converse
python scripts/test_elastic_agent_tools.py --list
```

## Architecture

### Agent Hierarchy

The system uses a **main orchestrator agent** (`agent.py`) that delegates to four specialized subagents:

1. **metrics-agent** (`subagents/metrics_agent.py`) - Fetches GitHub repository metrics (stars, commits, contributors, issue close rates)
2. **sentiment-agent** (`subagents/sentiment_agent.py`) - Analyzes community sentiment from issues and discussions
3. **web-agent** (`subagents/web_agent.py`) - Researches external adoption signals (blog posts, case studies, job postings)
4. **elastic-agent** (`subagents/elastic_agent.py`) - Queries Elasticsearch directly via native tools for semantic search, trend analysis, adoption signals, and report/discovery retrieval

The orchestrator coordinates these subagents in parallel, synthesizes their findings, and calculates a viability score.

### Agent Initialization

The agent uses **lazy initialization** to avoid import-time side effects:

```python
from agent import get_agent, reset_agent

# Get the singleton agent instance (created on first call)
agent = get_agent()
result = agent.invoke({"messages": [...]})

# For testing: reset the agent singleton
reset_agent()
```

This pattern ensures:
- No agent creation at import time (fast imports)
- Thread-safe singleton via double-checked locking
- Testable code (can mock or reset the agent)
- Configuration validated only when agent is first requested

### Elastic Agent Integration

The elastic-agent subagent queries Elasticsearch **directly** via native LangChain
tools (the ES client in `elasticsearch_tools.py`). It owns a set of read-only tools
and decides which to call — there is no round-trip through the Elastic Agent Builder
`/converse` endpoint. Every tool returns structured data (dicts/lists) the subagent
reasons over directly. Capabilities:
- **Semantic search** (`find_similar_technologies`) - Find similar technologies via vector embeddings
- **Trend analysis** (`get_trend_data`, `search_repo_timeseries`) - Historical snapshots and time-series
- **Adoption signals** (`search_adoption_signals`) - Blog posts, case studies, job postings
- **Reports** (`fetch_latest_report`, `fetch_cached_report`) - Past research reports
- **Subagent findings** (`fetch_subagent_findings`) - Stored per-subagent analyses; the orchestrator reuses fresh ones (metrics <24h, sentiment/web <7d) instead of re-running subagents
- **Discoveries** (`search_past_discoveries`, `list_discovered_repos`) - Prior discovery runs
- **Snapshots / tags** (`compare_technologies`, `search_by_tags`) - Latest stored snapshots

> **Legacy (dormant):** The Elastic Agent Builder path — `ask_elastic_agent` →
> `/converse`, the ES|QL tools in `elastic_agent_tools.md`, and the
> `scripts/create_elastic_agent*.py` provisioners — remains on disk for
> reference/fallback but is no longer wired into the agent.

### Tool Categories

Tools in `tools/` are split by domain:
- `github_tools.py` - GitHub API interactions (`fetch_repo_metrics`, `fetch_recent_issues`, `fetch_repo_discussions`)
- `elasticsearch_tools.py` - Persistent data storage and querying (direct ES client); several retrieval functions are `@tool`-decorated
- `elastic_search_tools.py` - Thin `@tool` wrappers over the ES retrieval helpers, used by the elastic-agent subagent (structured dict/list output)
- `cache.py` - Redis-backed cache for external API results (Tavily search, GitHub metrics, GitHub issues/discussions)
- `scoring_tools.py` - Viability scoring logic (`calculate_viability_score`)
- `elastic_agent_client.py` *(dormant)* - Client for the Elastic Agent Builder `/converse` + ES|QL endpoints
- `elastic_subagent_tools.py` *(dormant)* - The legacy `ask_elastic_agent` delegation tool

### GitHub API Optimizations

The GitHub tools include several performance and reliability features:

**Connection Pooling:**
```python
from tools import get_github_client, close_github_client

client = get_github_client()  # Singleton with HTTP/2, keepalive
# ... use client ...
close_github_client()  # Called automatically at exit
```

**Rate Limiting:**
```python
from tools import get_remaining_github_calls, get_github_rate_limit_stats

remaining = get_remaining_github_calls()  # Check available quota
stats = get_github_rate_limit_stats()     # Full usage statistics
# Rate limiter uses token bucket algorithm (1000 calls/hour limit)
```

**Datetime Parsing:**
- `parse_github_datetime()` helper function for efficient date parsing
- Dates parsed once per commit, reused across all calculations (4.4x faster)

### Data Storage

**Redis Cache** (ephemeral, expires via native key TTL — see `tools/cache.py`):
- `search:<hash>` - Cached Tavily search results (7-day TTL)
- `gh-metrics:<repo>` - Cached GitHub API responses (24-hour TTL)
- `gh-data:<repo>:<issues|discussions>` - Cached issues/discussions (24-hour TTL)

Redis expires these keys automatically, so there is no cleanup job or scheduled
expiry workflow. If Redis is unavailable the app still runs (every lookup is a miss).

**Elasticsearch Indices** (persistent, analytical data):
- `technology-research` - Main research snapshots with embeddings
- `repo-timeseries` - Point-in-time metrics for trend graphs
- `commit-history` - Weekly commit aggregates by author
- `adoption-signals` - Structured web findings (case studies, blog posts)
- `research-reports` - Final evaluation/comparison reports
- `subagent-findings` - Each research subagent's full narrative analysis, stored verbatim for freshness-window reuse

**File Output:**
- `research_reports/` - Markdown reports saved automatically after each evaluation/comparison

### Configuration

All configuration is managed through `config.py`, which loads from `.env`:
- API keys: `ANTHROPIC_API_KEY`, `TAVILY_API_KEY`, `GITHUB_TOKEN`, `ELASTICSEARCH_API_KEY`
- Elasticsearch: `ELASTICSEARCH_HOST`
- Redis cache: `REDIS_URL` (optional - defaults to `redis://localhost:6379/0`; app runs without it)
- Kibana/Elastic Agent: `KIBANA_URL` (optional - derived from ES host), `KIBANA_API_KEY` (optional - uses ES key)
- Observability: `LANGSMITH_API_KEY`, `LANGCHAIN_PROJECT`

The `Config.validate()` method checks for required environment variables at startup.

**Security Features:**
```python
from config import config, sanitize_for_logging

# Get safe config summary for logging (API keys masked)
summary = config.get_config_summary()
# {"ANTHROPIC_API_KEY": "sk-a***", "GITHUB_TOKEN": "ghp_***", ...}

# Sanitize arbitrary text that might contain secrets
safe_text = sanitize_for_logging(potentially_sensitive_text)
```

Sensitive keys are automatically detected and masked in logs.

### Prompts

System prompts in `prompts.py` define:
- Main orchestrator behavior and research workflow
- Output format templates for evaluations and comparisons
- Delegation rules and concurrency limits

### Error Handling

Custom exceptions in `exceptions.py`:
- `DevRelResearchError` - Base exception for all errors
- `GitHubAPIError` - GitHub API request failures
- `RateLimitError` - API rate limits exceeded (includes `retry_after` seconds)
- `ElasticsearchError` - Elasticsearch operation failures
- `ConfigurationError` - Missing or invalid configuration
- `SubAgentError` - Subagent task failures
- `ScoringError` - Viability scoring failures
- `SearchError` - Web search operation failures

## Code Quality

See `TODO.md` for the current improvement roadmap. Completed optimizations:
- API key sanitization in logs
- HTTP connection pooling for GitHub (30-50% faster)
- Rate limiting with token bucket algorithm
- Lazy agent initialization (no import-time side effects)
- Datetime parsing optimization (4.4x faster)
