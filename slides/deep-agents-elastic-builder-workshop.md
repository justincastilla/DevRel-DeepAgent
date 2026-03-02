# Building Multi-Agent Systems with DeepAgents & Elastic Agent Builder

---

## Workshop Overview

### What You'll Learn

1. **LangChain's DeepAgents Framework** — Hierarchical multi-agent orchestration
2. **Elastic Agent Builder** — ES|QL tools for intelligent data operations
3. **Hands-on Example** — DevRel Research Agent walkthrough

### Prerequisites

- Python 3.12+
- Basic LangChain knowledge
- Elasticsearch fundamentals

---

# Part 1: LangChain's DeepAgents Framework

---

## What is DeepAgents?

### The Problem

Traditional single-agent systems struggle with:
- Complex multi-step workflows
- Specialized domain knowledge
- Parallel task execution
- Context management at scale

### The Solution

**DeepAgents** provides hierarchical multi-agent orchestration:

```
┌─────────────────────────────────────────────────────┐
│               ORCHESTRATOR AGENT                     │
│         (Coordinates, delegates, synthesizes)        │
└───────┬───────────┬───────────┬───────────┬─────────┘
        │           │           │           │
   ┌────▼────┐ ┌────▼────┐ ┌────▼────┐ ┌────▼────┐
   │SubAgent │ │SubAgent │ │SubAgent │ │SubAgent │
   │    A    │ │    B    │ │    C    │ │    D    │
   └─────────┘ └─────────┘ └─────────┘ └─────────┘
```

SubAgents run **in parallel** when independent, then results are synthesized.

---

## Core Concepts

### 1. Orchestrator Agent

The **main coordinator** that:
- Receives user requests
- Decides which subagents to invoke
- Runs subagents in **parallel** when possible
- Synthesizes results into a unified response

### 2. SubAgents

**Specialized workers** that:
- Focus on a single domain
- Have their own tools and prompts
- Report back to the orchestrator

### 3. Tools

**Atomic operations** that:
- Connect to external APIs
- Perform calculations
- Store/retrieve data

---

## Agent Creation Pattern

```python
from deepagents import create_deep_agent

# Create the main orchestrator
agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-5-20250929",
    system_prompt=system_prompt,
    tools=[                    # Tools for THIS agent
        find_similar,
        calculate_score,
    ],
    subagents=[                # Agents to delegate to
        metrics_subagent,
        sentiment_subagent,
        web_subagent,
    ],
)
```

**Key Point**: The orchestrator has its own tools AND can delegate to subagents.

---

## SubAgent Definition

SubAgents are defined as dictionaries:

```python
metrics_subagent = {
    "name": "metrics-agent",
    
    "description": """Fetches GitHub repository metrics.
    Use when you need quantitative data about repo health.""",
    
    "system_prompt": """You are a GitHub Metrics Specialist.
    
    Your workflow:
    1. Use fetch_repo_metrics to get data
    2. Analyze patterns and trends
    3. Store snapshot for historical tracking
    4. Report findings with specific numbers""",
    
    "tools": [
        fetch_repo_metrics,
        store_research_snapshot,
    ],
}
```

---

## The Description Field is Critical

The `description` tells the orchestrator **when** to use this subagent:

```python
# ✅ Good - Specific and actionable
"description": """Fetches GitHub repository metrics including 
stars, commits, contributors, and issue close rates. Use this 
agent when you need quantitative health data about a repository."""

# ❌ Bad - Vague and unhelpful
"description": "Handles GitHub stuff"
```

**Think of it as**: What question does this agent answer?

---

## Parallel Execution

DeepAgents runs subagents **in parallel** when they're independent:

```python
# In the system prompt, guide parallel execution:
system_prompt = """
## Delegation Rules

When evaluating a repository:
1. Delegate to metrics-agent, sentiment-agent, and web-agent 
   IN PARALLEL (they don't depend on each other)
2. Wait for all results
3. Use elastic-agent to check historical data
4. Synthesize findings into final report
"""
```

**Performance Impact**: 3 agents × 10 seconds each = 10 seconds (not 30)

---

## Lazy Initialization Pattern

Avoid import-time side effects with lazy initialization:

```python
_agent = None
_agent_lock = threading.Lock()

def get_agent():
    global _agent
    
    # Fast path: already created
    if _agent is not None:
        return _agent
    
    # Thread-safe creation
    with _agent_lock:
        if _agent is None:
            _agent = create_deep_agent(...)
    
    return _agent
```

**Benefits**: Fast imports, testable code, thread-safe

---

## Real Example: DevRel Research Agent

### Architecture

```
                         ┌──────────────────┐
                         │   Orchestrator   │
                         │    (agent.py)    │
                         └────────┬─────────┘
                                  │
     ┌───────────────┬────────────┼────────────┬───────────────┐
     │               │            │            │               │
     ▼               ▼            ▼            ▼               ▼
┌─────────┐   ┌───────────┐  ┌─────────┐  ┌─────────┐   ┌───────────┐
│ metrics │   │ sentiment │  │   web   │  │ elastic │   │  scoring  │
│  agent  │   │   agent   │  │  agent  │  │  agent  │   │  (tools)  │
└────┬────┘   └─────┬─────┘  └────┬────┘  └────┬────┘   └───────────┘
     │              │             │            │
     ▼              ▼             ▼            ▼
 GitHub API    GitHub API    Tavily API   Elasticsearch
 (metrics)    (issues/PRs)   (adoption)   (ES|QL tools)
```

**Note**: The orchestrator also has direct tools (`calculate_viability_score`, `find_similar_technologies`) for cross-cutting operations.

---

## Orchestrator Tools vs SubAgent Tools

| Tool Location | Purpose | Example |
|---------------|---------|---------|
| **Orchestrator** | Cross-cutting concerns | `calculate_viability_score` |
| **SubAgent** | Domain-specific operations | `fetch_repo_metrics` |

```python
# Orchestrator-level tools (synthesis, scoring)
orchestrator_tools = [
    find_similar_technologies,   # Needs data from all agents
    calculate_viability_score,   # Combines all metrics
    store_research_report,       # Final output
]

# SubAgent-level tools (domain-specific)
metrics_tools = [
    fetch_repo_metrics,          # GitHub API calls
    store_research_snapshot,     # Raw data storage
]
```

---

## Tool File Organization

Tools are split by domain in the `tools/` directory:

| File | Purpose |
|------|---------|
| `github_tools.py` | GitHub API interactions (`fetch_repo_metrics`, `fetch_recent_issues`, `fetch_repo_discussions`) |
| `elasticsearch_tools.py` | Data persistence, caching, querying (direct ES client) |
| `elastic_agent_client.py` | HTTP client for invoking ES|QL tools on Elastic serverless agent |
| `elastic_subagent_tools.py` | LangChain tool wrappers (16 tools) |
| `scoring_tools.py` | Viability scoring logic (`calculate_viability_score`) |

---

## GitHub API Optimizations

Production agents need efficient, reliable API calls:

### Connection Pooling (30-50% faster)

```python
from tools import get_github_client, close_github_client

# Singleton client with HTTP/2 and keepalive
client = get_github_client()
# ... use client for multiple requests ...
close_github_client()  # Called automatically at exit
```

### Rate Limiting (Token Bucket Algorithm)

```python
from tools import get_remaining_github_calls, get_github_rate_limit_stats

remaining = get_remaining_github_calls()  # Check quota before batch
if remaining < 100:
    logger.warning("Low on GitHub API quota")

stats = get_github_rate_limit_stats()  # Full usage breakdown
# Limit: 1000 calls/hour with token bucket replenishment
```

### Datetime Parsing (4.4x faster)

```python
from tools.github_tools import parse_github_datetime

# Parse once, reuse across calculations
commit_date = parse_github_datetime(commit["committedDate"])
# Efficient for processing hundreds of commits
```

---

# Part 2: Elastic Agent Builder

---

## What is Elastic Agent Builder?

### The Concept

A **no-code/low-code** way to create AI agent tools that:
- Execute **ES|QL queries** against Elasticsearch
- Are callable via the **Kibana API**
- Support **parameterized queries** for security
- Enable **semantic search** with vector embeddings

### Why Use It?

- Centralize data access logic in Elasticsearch
- Share tools across multiple agents
- Leverage ES|QL's powerful analytics
- Built-in security and rate limiting

---

## ES|QL Primer

**ES|QL** (Elasticsearch Query Language) — A pipe-based query language:

```esql
FROM technology-research
| WHERE repo == "langchain-ai/langgraph"
| WHERE timestamp > "2025-01-01"
| SORT timestamp DESC
| KEEP repo, timestamp, analysis.viability_score
| LIMIT 10
```

**Key Operators**:
- `FROM` — Source index
- `WHERE` — Filter conditions
- `SORT` — Ordering
- `KEEP` — Select fields (like SQL SELECT)
- `STATS` — Aggregations

---

## ES|QL Semantic Search

Use `semantic_text` field type for vector search:

```esql
FROM technology-research METADATA _score
| WHERE semantic_content:"AI agent frameworks for Python"
| SORT _score DESC
| KEEP repo, analysis.summary, _score
| LIMIT 5
```

**Key Requirements**:
1. `METADATA _score` — Include relevance scores
2. Field mapped as `semantic_text` type
3. `SORT _score DESC` — Rank by relevance

---

## Creating Tools via Kibana API

### API Endpoint

```http
POST kbn:/api/agent_builder/tools
```

### Headers Required

```http
kbn-xsrf: true
Authorization: ApiKey ${API_KEY}
Content-Type: application/json
```

---

## Tool Definition Structure

```json
POST kbn:/api/agent_builder/tools
{
  "id": "find-similar-technologies",
  "type": "esql",
  "description": "Semantic search to find similar technologies",
  "tags": ["search", "semantic"],
  "configuration": {
    "query": "FROM technology-research METADATA _score 
              | WHERE semantic_content:?description 
              | SORT _score DESC 
              | KEEP repo, analysis.summary, _score 
              | LIMIT ?limit",
    "params": {
      "description": {
        "type": "text",
        "description": "What you're looking for",
        "required": true
      },
      "limit": {
        "type": "integer",
        "description": "Max results",
        "default": 5
      }
    }
  }
}
```

---

## Parameterized Queries

**Always use parameters** — Never concatenate user input!

```esql
# ✅ Safe - Parameterized
FROM technology-research
| WHERE repo == ?repo_name

# ❌ Dangerous - String concatenation
FROM technology-research
| WHERE repo == "${user_input}"
```

### Parameter Types

| Type | ES|QL Syntax | Example |
|------|-------------|---------|
| Text | `?param` | `?description` |
| Integer | `?param` | `?limit` |
| Date | `?param` | `?start_date` |

---

## Tool Categories (16 ES|QL Tools)

### Search & Discovery
| Tool | Purpose |
|------|---------|
| `find-similar-technologies` | Semantic search via vector embeddings |
| `search-by-tags` | Tag-based filtering with viability threshold |
| `search-discoveries-by-use-case` | Find past discoveries by use case |

### Trend & Time-Series Analysis
| Tool | Purpose |
|------|---------|
| `get-trend-data` | Historical snapshots for trend analysis |
| `get-repo-timeseries` | Detailed metrics over time |
| `get-repo-timeseries-stats` | Aggregated statistics (avg, min, max) |

### Cache Tools (Cost Reduction)
| Tool | Purpose |
|------|---------|
| `get-cached-search` | Web search cache (7-day TTL) |
| `get-cached-github-metrics` | GitHub API cache (24-hour TTL) |
| `get-cached-report` | Research report cache |

### Adoption Signals
| Tool | Purpose |
|------|---------|
| `get-adoption-signals` | All adoption signals for a repo |
| `get-adoption-signals-by-type` | Filter by: blog_post, case_study, job_posting |
| `count-adoption-signals` | Aggregate counts by signal type |

### Reports & Snapshots
| Tool | Purpose |
|------|---------|
| `get-latest-snapshot` | Most recent research snapshot |
| `get-latest-report` | Most recent research report |
| `get-past-discoveries` | Historical discovery results |
| `get-all-discovered-repos` | All tracked repositories |

---

## LangChain Tool Wrappers

Wrap ES|QL tools for LangChain:

```python
from langchain_core.tools import tool

@tool
def semantic_search_technologies(description: str, limit: int = 5) -> dict:
    """
    Search for similar technologies using semantic search.
    
    Args:
        description: What you're looking for
        limit: Maximum results (default: 5)
    
    Returns:
        Search results with repos and scores
    """
    client = get_elastic_agent_client()
    
    return client.invoke_tool(
        "find-similar-technologies",
        {
            "description": description,
            "limit": limit,
        }
    )
```

---

## The Elastic Agent Client

HTTP client for Kibana Agent Builder API:

```python
class ElasticAgentClient:
    def __init__(self, kibana_url: str, api_key: str):
        self.base_url = kibana_url
        self.client = httpx.Client(
            headers={
                "kbn-xsrf": "true",
                "Authorization": f"ApiKey {api_key}",
            }
        )
    
    def invoke_tool(self, tool_id: str, params: dict) -> dict:
        response = self.client.post(
            f"{self.base_url}/api/agent_builder/tools/{tool_id}/invoke",
            json={"params": params}
        )
        return response.json()
```

---

## Elastic SubAgent Design

```python
elastic_subagent = {
    "name": "elastic-agent",
    
    "description": """Interfaces with Elasticsearch for all data 
    operations. Use when you need to:
    - Search for similar technologies
    - Retrieve historical trends
    - Check caches before API calls
    - Get adoption signals and reports""",
    
    "system_prompt": """You are an Elastic Data Specialist.
    
    ## Best Practices You Demonstrate
    1. ES|QL queries with parameterized inputs
    2. Semantic search with METADATA _score
    3. Check caches before expensive API calls
    4. Use STATS for aggregations""",
    
    "tools": ELASTIC_SUBAGENT_TOOLS,  # 16 tools
}
```

---

# Part 3: Putting It Together

---

## Data Flow Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     USER REQUEST                            │
│    "Evaluate langchain-ai/langgraph" or natural language    │
│    "What are the best Python web frameworks?"               │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                     ORCHESTRATOR                            │
│  1. Parse request                                           │
│  2. Check elastic-agent for cached/historical data          │
│  3. Delegate to subagents IN PARALLEL                       │
└──────┬──────────────┬──────────────┬──────────────┬─────────┘
       │              │              │              │
       ▼              ▼              ▼              ▼
  ┌─────────┐   ┌──────────┐   ┌─────────┐   ┌──────────┐
  │ Metrics │   │Sentiment │   │   Web   │   │ Elastic  │
  │  Agent  │   │  Agent   │   │  Agent  │   │  Agent   │
  └────┬────┘   └────┬─────┘   └────┬────┘   └────┬─────┘
       │              │              │              │
       ▼              ▼              ▼              ▼
  GitHub API    GitHub API     Tavily API    Elasticsearch
  (GraphQL)    (Issues/PRs)   (Web Search)  (16 ES|QL Tools)
       │              │              │              │
       └──────────────┴──────────────┴──────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                     ORCHESTRATOR                            │
│  4. Synthesize findings from all agents                     │
│  5. Calculate viability score (orchestrator tool)           │
│  6. Store snapshot + report via elastic-agent               │
│  7. Save markdown report to research_reports/               │
└─────────────────────────────────────────────────────────────┘
```

---

## Elasticsearch Index Architecture

Seven indices power the research workflow:

| Index | Purpose | TTL |
|-------|---------|-----|
| `technology-research` | Main snapshots with embeddings | - |
| `web-search-cache` | Cached Tavily search results | 7 days |
| `github-metrics-cache` | Cached GitHub API responses | 24 hours |
| `repo-timeseries` | Point-in-time metrics for trends | - |
| `commit-history` | Weekly commit aggregates by author | - |
| `adoption-signals` | Blog posts, case studies, job postings | - |
| `research-reports` | Final evaluation/comparison reports | - |

```bash
# Setup all indices (run once)
python scripts/setup_elasticsearch.py
```

---

## Caching Strategy

### Check Cache → Call API → Store Result

```python
@tool
def search_adoption_signals(query: str) -> dict:
    """Search for adoption signals with caching."""

    # 1. Check cache first (ES|QL tool: get-cached-search)
    cached = check_search_cache(query)
    if cached and not cached.get("expired"):
        logger.info(f"Cache HIT for: {query}")
        return cached["results"]

    # 2. Call external API
    logger.info(f"Cache MISS, searching: {query}")
    results = tavily_client.search(query)

    # 3. Store in cache (7-day TTL)
    store_search_cache(query, results, ttl_hours=168)

    return results
```

**ES|QL Tool**: `get-cached-search` checks the `web-search-cache` index

---

## Configuration Management

All configuration via `config.py` loading from `.env`:

```bash
# Required API Keys
ANTHROPIC_API_KEY=sk-ant-...     # Claude model access
TAVILY_API_KEY=tvly-...          # Web search
GITHUB_TOKEN=ghp_...             # GitHub API (higher rate limits)
ELASTICSEARCH_API_KEY=...        # Elasticsearch access

# Elasticsearch
ELASTICSEARCH_HOST=https://your-cluster.es.cloud.example.com

# Kibana/Elastic Agent (optional - derived from ES host if omitted)
KIBANA_URL=https://your-cluster.kb.cloud.example.com
KIBANA_API_KEY=...               # Uses ES key if omitted

# Observability (optional but recommended)
LANGSMITH_API_KEY=ls__...        # LangSmith tracing
LANGCHAIN_PROJECT=devrel-research
```

**Validation**: `Config.validate()` checks required vars at startup.

---

## Error Handling Pattern

Custom exceptions for each failure mode in `exceptions.py`:

```python
class DevRelResearchError(Exception):
    """Base exception for all errors"""

class GitHubAPIError(DevRelResearchError):
    """GitHub API request failures"""

class RateLimitError(DevRelResearchError):
    """API rate limits exceeded"""
    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after  # Seconds to wait

class ElasticsearchError(DevRelResearchError):
    """Elasticsearch operation failures"""

class ConfigurationError(DevRelResearchError):
    """Missing or invalid configuration"""

class SubAgentError(DevRelResearchError):
    """Subagent task failures"""

class ScoringError(DevRelResearchError):
    """Viability scoring failures"""

class SearchError(DevRelResearchError):
    """Web search operation failures (Tavily)"""
```

**Why Custom Exceptions?** Enables targeted retry logic and graceful degradation per failure type.

---

## Retry Logic

Exponential backoff for transient failures:

```python
from utils.retry_utils import with_retry

@with_retry(max_attempts=3, backoff_factor=2)
def fetch_repo_metrics(repo: str) -> dict:
    """Fetch with automatic retry on failure."""
    response = client.post(GITHUB_GRAPHQL_URL, json=query)

    if response.status_code == 429:
        raise RateLimitError("Rate limited", retry_after=60)

    return response.json()
```

**Retry Schedule**: 1s → 2s → 4s (with jitter)

---

## Security: API Key Sanitization

**Never log raw API keys** — Use sanitization helpers:

```python
from config import config, sanitize_for_logging

# Get safe config summary for logging (keys masked)
summary = config.get_config_summary()
# {"ANTHROPIC_API_KEY": "sk-a***", "GITHUB_TOKEN": "ghp_***", ...}

# Sanitize arbitrary text that might contain secrets
safe_text = sanitize_for_logging(potentially_sensitive_text)
logger.info(f"Request details: {safe_text}")
```

**Pattern Detection**: Automatically masks keys matching common patterns:
- `sk-ant-*` (Anthropic)
- `ghp_*` (GitHub)
- API keys in URLs or JSON

---

## File Output

Reports are automatically saved after each evaluation/comparison:

```
research_reports/
├── langchain-ai_langgraph_2025-01-29.md
├── comparison_crewai_vs_autogen_2025-01-28.md
└── discovery_ui-frameworks_2025-01-27.md
```

**Export Options**:
```bash
# Custom output path and format
python cli.py evaluate langchain-ai/langgraph \
    --output custom-report.md \
    --format markdown
```

---

## System Prompt Best Practices

```python
ORCHESTRATOR_PROMPT = """
## Your Mission
Help DevRel teams evaluate technologies for coverage.

## Your Workflow
1. UNDERSTAND the request
2. PLAN research (use write_todos)
3. DELEGATE to specialists IN PARALLEL
4. SYNTHESIZE findings
5. DELIVER actionable report
6. SAVE report for future reference

## Delegation Rules
- metrics-agent: Quantitative GitHub data
- sentiment-agent: Community health
- web-agent: External adoption signals
- elastic-agent: Historical data, caching

## Quality Standards
Always include:
- Exact numbers (not "many stars")
- Source URLs (GitHub, docs, blog posts)
- Specific findings (company names, issue titles)
"""
```

---

## Output Format Requirements

Force structured, complete output:

```python
OUTPUT_FORMAT = """
## CRITICAL REQUIREMENTS

1. **MINIMUM LENGTH**: 1500+ words
2. **ALL METRICS WITH NUMBERS**: 
   - "24,532 stars" not "many stars"
3. **MINIMUM 3 LINKS**:
   - GitHub repo (REQUIRED)
   - Documentation (REQUIRED)  
   - Homepage (REQUIRED)
4. **TABLES FOR METRICS**:
   | Metric | Value | Assessment |
   |--------|-------|------------|
   | Stars  | 24,532| Excellent  |
"""
```

---

# Hands-On Exercise

---

## Exercise 1: Create a New SubAgent

**Task**: Create a `license-agent` that analyzes open source licenses.

```python
# subagents/license_agent.py

from tools import fetch_license_info

license_subagent = {
    "name": "license-agent",
    "description": """???""",  # Your turn!
    "system_prompt": """???""", # Your turn!
    "tools": [fetch_license_info],
}
```

**Hints**:
- What question does this agent answer?
- What should it look for? (MIT, Apache, GPL, etc.)
- What are the warning signs?

---

## Exercise 2: Create an ES|QL Tool

**Task**: Create a tool to find repos by license type.

```json
POST kbn:/api/agent_builder/tools
{
  "id": "find-by-license",
  "type": "esql",
  "description": "???",
  "configuration": {
    "query": "???",
    "params": {
      "license": {
        "type": "text",
        "description": "License type to search for"
      }
    }
  }
}
```

**Hint**: `FROM technology-research | WHERE metrics.license == ?license`

---

## Exercise 3: Add Parallel Execution

**Task**: Modify the orchestrator to run your new license-agent in parallel.

```python
# agent.py

from subagents import (
    metrics_subagent,
    sentiment_subagent, 
    web_subagent,
    elastic_subagent,
    license_subagent,  # Add this
)

_agent = create_deep_agent(
    ...
    subagents=[
        metrics_subagent,
        sentiment_subagent,
        web_subagent,
        elastic_subagent,
        license_subagent,  # Add this
    ],
)
```

---

# Key Takeaways

---

## DeepAgents Framework

1. **Orchestrator + SubAgents** = Hierarchical multi-agent systems
2. **Description field** tells the orchestrator when to delegate
3. **Parallel execution** for independent subagents
4. **Lazy initialization** avoids import-time side effects
5. **Tools belong** where they're most relevant

---

## Elastic Agent Builder

1. **ES|QL tools** centralize data access in Elasticsearch
2. **Parameterized queries** prevent injection attacks
3. **Semantic search** uses `semantic_text` + `METADATA _score`
4. **LangChain wrappers** make ES|QL tools callable by agents
5. **Caching** reduces API costs and latency

---

## Best Practices

| Category | Practice |
|----------|----------|
| **Architecture** | Separate concerns into specialized agents |
| **Performance** | Parallel execution, connection pooling (30-50% faster), caching |
| **Security** | Parameterized ES|QL, `sanitize_for_logging()` for API keys |
| **Reliability** | Retry logic with backoff, custom exceptions, graceful degradation |
| **Observability** | Structured logging, LangSmith tracing, verbose mode (`-v`) |

---

## Observability & Debugging

### Verbose Mode

See real-time agent activity during execution:

```bash
python cli.py ask "Compare MongoDB and Elasticsearch" --verbose
python cli.py compare mongodb/mongo elastic/elasticsearch -v
```

### LangSmith Integration

Full trace visibility for debugging multi-agent flows:

```bash
# In .env
LANGSMITH_API_KEY=ls__...
LANGCHAIN_PROJECT=devrel-research
```

View traces at: https://smith.langchain.com

---

# Resources

---

## Documentation

- **DeepAgents**: [LangChain Docs](https://docs.langchain.com/deepagents)
- **ES|QL**: [Elastic Docs](https://www.elastic.co/guide/en/elasticsearch/reference/current/esql.html)
- **Agent Builder**: [Kibana Docs](https://www.elastic.co/guide/en/kibana/current/agent-builder.html)

## This Project

- **GitHub**: `github.com/your-org/DeepDevRel`
- **CLAUDE.md**: Project guidance for AI assistants
- **elastic_agent_tools.md**: All 16 ES|QL tool definitions

## Community

- LangChain Discord
- Elastic Community Forums

---

# Thank You!

## Questions?

### Next Steps

1. Clone the DeepDevRel repo
2. Set up your `.env` file with required keys:
   - `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, `TAVILY_API_KEY`
   - `ELASTICSEARCH_HOST`, `ELASTICSEARCH_API_KEY`
   - Optional: `LANGSMITH_API_KEY` for observability
3. Run `python scripts/setup_elasticsearch.py`
4. Try these CLI commands:

```bash
# Natural language queries (most powerful)
python cli.py ask "What are the best Python web frameworks?"
python cli.py ask "Compare MongoDB vs PostgreSQL for analytics" -v

# Discover technologies for a use case
python cli.py discover "UI frameworks for multi-modal AI chat"

# Evaluate a specific repository
python cli.py evaluate langchain-ai/langgraph --use-case "building agents"

# Compare multiple repositories
python cli.py compare crewAIInc/crewAI microsoft/autogen

# Search previously researched technologies
python cli.py search "AI agent frameworks" --tags ai-agents python
```

5. Explore `research_reports/` for saved markdown reports
6. Read `elastic_agent_tools.md` for all 16 ES|QL tool definitions

---

*Slides created for DeepAgents & Elastic Agent Builder Workshop*
