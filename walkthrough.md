# DevRel Research Agent — Walkthrough

## What is LangChain DeepAgents?

[DeepAgents](https://docs.langchain.com/oss/python/deepagents/overview) is a LangChain library (built on LangGraph) for creating hierarchical multi-agent systems. It provides a pattern where a single **orchestrator agent** can spawn, delegate to, and coordinate multiple **subagents** — each a focused specialist with its own tools and system prompt.

Key concepts:

- **`create_deep_agent`** — factory function that wires together the orchestrator LLM, its direct tools, and its pool of subagents into a LangGraph runnable.
- **Subagents** — each defined as a dict with `name`, `description`, `system_prompt`, and `tools`. The orchestrator sees their `description` and uses a `task()` tool to delegate work to them.
- **`task()` tool** — built-in DeepAgents mechanism that lets the orchestrator spin up a subagent, pass it a natural-language instruction, and receive its output. Subagents can be run in parallel.
- **`write_todos` / `read_todos`** — built-in tools that let the orchestrator maintain a research plan (a checklist) across turns.
- **Middleware** — optional layers (memory, filesystem) that can be attached to any agent in the hierarchy.

The library handles all the LangGraph state management, message routing between agents, and tool execution loop internally. You only define the agents and their tools; DeepAgents handles the rest.

---

## Application Overview

**DevRel Research Agent** helps Developer Advocates evaluate technologies. Given a natural-language query (e.g., "Compare CrewAI vs AutoGen for multi-agent orchestration"), it:

1. Searches Elasticsearch for prior research
2. Fetches live GitHub health metrics
3. Analyzes community sentiment from issues/discussions
4. Scrapes the web for real-world adoption signals
5. Calculates a viability score
6. Delivers a structured report and saves it for future reference

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Agent framework | LangChain DeepAgents (LangGraph) |
| LLM | Claude Sonnet (via Azure Anthropic Foundry) |
| Data store | Elasticsearch (Elastic Cloud) — persistent data |
| Cache | Redis (`redis:7-alpine`) — ephemeral API results |
| Elastic Agent | Elastic Agent Builder (`/converse` endpoint) |
| Web search | Tavily API |
| GitHub data | GitHub GraphQL API |
| Web UI | FastAPI + WebSockets |
| Observability | LangSmith |

---

## Agent Hierarchy

```
┌─────────────────────────────────────────────────────┐
│              Orchestrator Agent (agent.py)           │
│                                                     │
│  Direct tools:                                      │
│    • calculate_viability_score                      │
│    • store_research_report                          │
│                                                     │
│  Subagents (delegated via task()):                  │
│    ┌──────────────┐  ┌──────────────┐              │
│    │ elastic-agent│  │metrics-agent │              │
│    └──────────────┘  └──────────────┘              │
│    ┌──────────────┐  ┌──────────────┐              │
│    │sentiment-    │  │web-research- │              │
│    │agent         │  │agent         │              │
│    └──────────────┘  └──────────────┘              │
└─────────────────────────────────────────────────────┘
```

### Subagent Responsibilities

| Subagent | Tools | What it does |
|----------|-------|--------------|
| **elastic-agent** | `ask_elastic_agent` | Queries historical Elasticsearch data via Elastic Agent Builder — cached reports, snapshots, adoption signals, semantic search |
| **metrics-agent** | `fetch_repo_metrics`, `store_research_snapshot` | Fetches GitHub stars, forks, commit velocity, contributors, issue close rate via GraphQL API |
| **sentiment-agent** | `fetch_recent_issues`, `fetch_repo_discussions`, `store_research_snapshot` | Reads GitHub issues and discussions, classifies sentiment, flags red flags, assesses maintainer responsiveness |
| **web-research-agent** | `tavily_search`, `record_adoption_signal` | Searches the web for blog posts, case studies, conference talks, job postings; saves notable findings as adoption signals |

---

## How Elastic Agent Builder is Integrated

The **Elastic Agent Builder** is a feature in Elastic Kibana that lets you create AI agents backed by your Elasticsearch data. This application uses it as a specialized read-only data layer.

### The Agent

A custom agent called `devrel-research-agent` lives inside Elastic Agent Builder. It is configured with:

- A detailed **system prompt** covering all index schemas, ES|QL query patterns, and response format rules
- Five **platform tools**: `generate_esql`, `execute_esql`, `search`, `index_explorer`, `get_index_mapping`

When queried, this agent writes its own ES|QL queries, executes them, and returns structured results.

### How the Application Calls It

```
elastic-agent subagent
    └─→ ask_elastic_agent(query="Get latest report for crewAIInc/crewAI")
            └─→ ElasticAgentClient.chat()
                    └─→ POST /api/agent_builder/converse
                            └─→ Elastic Agent Builder (devrel-research-agent)
                                    └─→ generate_esql → execute_esql → response
```

The `elastic-agent` subagent sends **natural-language queries** to the Elastic Agent via the `/converse` endpoint. The Elastic Agent handles all ES|QL construction and execution internally and returns a formatted answer. This keeps the Python codebase clean — there is only one tool (`ask_elastic_agent`) rather than one tool per query type.

### Elasticsearch Indices

| Index | Purpose |
|-------|---------|
| `technology-research` | Main snapshots: stars, forks, commits, scores, embeddings |
| `research-reports` | Full evaluation and comparison reports |
| `repo-timeseries` | Point-in-time metrics for trend graphs |
| `adoption-signals` | Web-sourced evidence: blog posts, case studies, job postings |
| `technology-discoveries` | Discovery run results |

> These indices hold **persistent** data. Ephemeral API-result caching (Tavily results, GitHub metrics, GitHub issues/discussions) moved out of Elasticsearch into Redis — see the [Caching Strategy](#caching-strategy) section.

---

## End-to-End Flow

### Direct Evaluation (`evaluate langchain-ai/deepagents`)

```
User query
    │
    ▼
Orchestrator — understands request, writes a research plan (write_todos)
    │
    ├─→ elastic-agent: "Check for existing report and snapshot for langchain-ai/deepagents"
    │       └─→ Elastic Agent Builder queries research-reports + technology-research
    │           Returns: cached scores, prior summary (or "not found")
    │
    ├─→ metrics-agent: "Fetch GitHub metrics for langchain-ai/deepagents"          ┐
    │       └─→ GitHub GraphQL API → stars, forks, commits, contributors           │ parallel
    │           Stores snapshot in technology-research                              │
    │                                                                               │
    ├─→ sentiment-agent: "Analyze issues and discussions for langchain-ai/deepagents" │
    │       └─→ GitHub GraphQL API → recent issues + discussions                   │
    │           Returns: sentiment score, red flags, maintainer rating              ┘
    │
    └─→ web-research-agent: "Find adoption signals for deepagents"
            └─→ Tavily searches (tutorials, case studies, job postings)
                Saves notable findings as adoption-signals in Elasticsearch
    │
    ▼
Orchestrator — receives all subagent reports
    │
    ├─→ calculate_viability_score(health, community, adoption metrics)
    │
    ├─→ store_research_report(repo, scores, full_report, recommendation)
    │       └─→ Saves to research-reports index
    │
    └─→ Final report delivered to user (Markdown)
```

### Discovery Query (`"What are the top frameworks for X?"`)

```
User query
    │
    ▼
Orchestrator — identifies this as a discovery query (no specific repo known)
    │
    ├─→ elastic-agent: "Find technologies similar to X, check prior discoveries"
    │
    ├─→ web-research-agent: "Find top frameworks for X, identify GitHub repos"
    │       └─→ Returns: list of candidates with GitHub repos
    │
    ▼
Orchestrator — extracts repos from discovery results, starts Phase 2
    │
    ├─→ metrics-agent: candidate repo 1    ┐
    ├─→ metrics-agent: candidate repo 2    │ parallel per candidate
    ├─→ sentiment-agent: candidate repo 1  │
    ├─→ sentiment-agent: candidate repo 2  ┘
    │       (if no GitHub repo found → noted as "No GitHub repo — web sources only")
    │
    ▼
Orchestrator — comparison report across all candidates → store + deliver
```

---

## Caching Strategy

Ephemeral caches are checked before hitting external APIs to reduce latency and API costs. They live in **Redis** (`tools/cache.py`), keyed by content, with a native per-key TTL. The hit/miss flow is unchanged — check Redis first, return on HIT, otherwise call the API and store the result with a TTL:

```
fetch_repo_metrics()
    └─→ check Redis key gh-metrics:<repo> (24h TTL)
        ├─→ HIT  → return cached data (badge: "cache hit")
        └─→ MISS → GitHub GraphQL API → store in Redis with TTL (badge: "cache miss")

fetch_recent_issues() / fetch_repo_discussions()
    └─→ check Redis key gh-data:<repo>:<issues|discussions> (24h TTL)
        ├─→ HIT  → return cached list
        └─→ MISS → GitHub GraphQL API → store in Redis with TTL

tavily_search()
    └─→ check Redis key search:<hash> (7d TTL)
        ├─→ HIT  → return cached results
        └─→ MISS → Tavily API → store in Redis with TTL
```

Because Redis expires keys automatically via their TTL, there is **no cleanup job or startup step** — the old Elasticsearch `delete_by_query` pass and the scheduled cleanup workflow were removed. Caching is also **optional**: if `REDIS_URL` is unset or Redis is unreachable, every lookup simply becomes a MISS and the app keeps working (just slower).

Report caching is different and still lives in Elasticsearch — `ask_elastic_agent()` reads the persistent `research-reports` index for prior evaluations:

```
ask_elastic_agent()
    └─→ check research-reports (max_age_days param)
        ├─→ HIT  → return existing report (historical context only)
        └─→ MISS → "no data found" (triggers fresh research)
```

---

## Key Files

```
agent.py                        # Orchestrator: create_deep_agent() wiring
prompts.py                      # System prompts for orchestrator + delegation rules
config.py                       # All env var loading (ANTHROPIC, ELASTICSEARCH, etc.)

subagents/
    elastic_agent.py            # elastic-agent: sends NL queries to Elastic Agent Builder
    metrics_agent.py            # metrics-agent: GitHub quantitative analysis
    sentiment_agent.py          # sentiment-agent: issues/discussions qualitative analysis
    web_agent.py                # web-research-agent: Tavily adoption research

tools/
    elastic_agent_client.py     # HTTP client for Elastic Agent Builder /converse endpoint
    elastic_subagent_tools.py   # ask_elastic_agent LangChain tool (single entry point)
    elasticsearch_tools.py      # Direct ES client: store/retrieve snapshots, signals
    cache.py                    # Redis-backed ephemeral cache (Tavily, GitHub metrics/data)
    github_tools.py             # GitHub GraphQL: metrics, issues, discussions (pooled, rate-limited)
    scoring_tools.py            # calculate_viability_score()
    web_tools.py                # tavily_search(), record_adoption_signal()

scripts/
    create_elastic_agent.py     # Provisions devrel-research-agent in Elastic Agent Builder
    setup_elasticsearch.py      # Creates all index mappings

web_app.py                      # FastAPI app: WebSocket streaming, UI event bridge
cli.py                          # CLI entry point (ask / evaluate / compare / discover)
```

---

## Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Set up Elasticsearch indices (first time only)
python scripts/setup_elasticsearch.py

# Create / update the Elastic Agent Builder agent (first time only)
python scripts/create_elastic_agent.py

# Start the web UI
uvicorn web_app:app --reload

# Or use the CLI directly
python cli.py ask "Compare CrewAI vs AutoGen for multi-agent orchestration"
python cli.py evaluate langchain-ai/langgraph
python cli.py discover "UI frameworks for AI chat interfaces"
```
