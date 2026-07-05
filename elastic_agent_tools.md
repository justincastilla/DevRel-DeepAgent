# Elastic Agent ES|QL Tools

This document defines ES|QL tools to replace direct Elasticsearch client calls with queries routed through the Elastic serverless agent.

## Overview

Each tool below corresponds to a search operation in `tools/elasticsearch_tools.py`. These tools are created via the Kibana Agent Builder API and executed through the Elastic agent.

> **Ephemeral caching moved to Redis.** The former cache tools `get-cached-search` and `get-cached-github-metrics` (and their `web-search-cache` / `github-metrics-cache` / `github-data-cache` indices) have been removed. That caching now lives in Redis (`tools/cache.py`) with native per-key TTLs. The `get-cached-report` tool is unaffected — it reads the persistent `research-reports` index and stays here.

---

## Dev Tools API Reference

### Authentication Headers

All API calls require these headers:

```http
kbn-xsrf: true
Authorization: ApiKey ${API_KEY}
Content-Type: application/json
```

### API Endpoint

```http
POST kbn:/api/agent_builder/tools
```

For curl/external calls:

```bash
POST https://${KIBANA_URL}/api/agent_builder/tools
```

---

## ES|QL Semantic Search

ES|QL supports semantic search when fields are mapped as `semantic_text` type (available since 8.18/9.0).

### Syntax Option 1: Match Operator (`:`)

```esql
FROM technology-research METADATA _score
| WHERE semantic_content:"AI agent frameworks"
| SORT _score DESC
| LIMIT 5
```

### Syntax Option 2: Match Function

```esql
FROM technology-research METADATA _score
| WHERE match(semantic_content, "AI agent frameworks")
| SORT _score DESC
| LIMIT 5
```

### Key Requirements

1. **METADATA Declaration**: Include `METADATA _score` to calculate relevance scores
2. **Sorting**: Use `SORT _score DESC` to rank results by relevance
3. **Field Type**: The field must be mapped as `semantic_text` type

### Hybrid Search (Semantic + Lexical)

Combine semantic and traditional search with custom boost weights:

```esql
FROM technology-research METADATA _score
| WHERE match(semantic_content, "agent frameworks", {"boost": 0.75})
   OR match(repo, "langchain", {"boost": 0.25})
| SORT _score DESC
| LIMIT 10
```

---

## Tool Definitions

### 1. Find Similar Technologies

**Original Function:** `find_similar_technologies()` (line 157)

**Purpose:** Semantic search to find similar technologies in research history.

**Dev Tools Command:**

```json
POST kbn:/api/agent_builder/tools
{
  "id": "find-similar-technologies",
  "type": "esql",
  "description": "Use semantic search to find technologies similar to a given description. Returns repositories with metrics and analysis that match the search criteria.",
  "tags": ["search", "semantic", "technology-research"],
  "configuration": {
    "query": "FROM technology-research METADATA _score | WHERE semantic_content:?description | SORT _score DESC | KEEP repo, timestamp, tags, analysis.viability_score, analysis.summary, _score | LIMIT ?limit",
    "params": {
      "description": {
        "type": "string",
        "description": "Natural language description of the technology or use case to search for"
      },
      "limit": {
        "type": "integer",
        "description": "Maximum number of results to return (default 5)"
      }
    }
  }
}
```

---

### 2. Get Trend Data

**Original Function:** `get_trend_data()` (line 206)

**Purpose:** Query historical snapshots to identify trends for a repository.

**Note:** ES|QL parameters cannot be used within date math expressions. Pass an ISO date string for the `start_date` parameter instead of a number of days.

**Dev Tools Command:**

```json
POST kbn:/api/agent_builder/tools
{
  "id": "get-trend-data",
  "type": "esql",
  "description": "Retrieve historical snapshots for a repository to analyze trends in stars, issues, and viability scores over time.",
  "tags": ["trends", "analytics", "technology-research"],
  "configuration": {
    "query": "FROM technology-research | WHERE repo == ?repo_name AND timestamp >= ?start_date | SORT timestamp ASC | KEEP repo, timestamp, metrics.stars, metrics.open_issues, analysis.viability_score | LIMIT 100",
    "params": {
      "repo_name": {
        "type": "string",
        "description": "Full repository name (e.g., 'langchain-ai/deepagents')"
      },
      "start_date": {
        "type": "date",
        "description": "Start date for trend analysis in ISO format (e.g., '2024-10-01T00:00:00Z')"
      }
    }
  }
}
```

---

### 3. Compare Technologies

**Original Function:** `compare_technologies()` (line 291)

**Purpose:** Get most recent snapshot for a repository to compare side-by-side.

**Dev Tools Command:**

```json
POST kbn:/api/agent_builder/tools
{
  "id": "get-latest-snapshot",
  "type": "esql",
  "description": "Get the most recent research snapshot for a repository. Use this to compare multiple technologies by calling once per repo.",
  "tags": ["comparison", "snapshot", "technology-research"],
  "configuration": {
    "query": "FROM technology-research | WHERE repo == ?repo_name | SORT timestamp DESC | KEEP repo, timestamp, metrics.stars, metrics.forks, metrics.open_issues, metrics.contributors, analysis.viability_score, analysis.risk_flags | LIMIT 1",
    "params": {
      "repo_name": {
        "type": "string",
        "description": "Full repository name (e.g., 'langchain-ai/deepagents')"
      }
    }
  }
}
```

---

### 4. Search by Tags

**Original Function:** `search_by_tags()` (line 352)

**Purpose:** Search technologies by tags with optional viability filter.

**Dev Tools Command:**

```json
POST kbn:/api/agent_builder/tools
{
  "id": "search-by-tags",
  "type": "esql",
  "description": "Search for technologies by tags (e.g., 'ai-agents', 'python') with an optional minimum viability score filter.",
  "tags": ["search", "tags", "technology-research"],
  "configuration": {
    "query": "FROM technology-research | WHERE tags LIKE ?tag_pattern AND analysis.viability_score >= ?min_viability | SORT analysis.viability_score DESC, timestamp DESC | KEEP repo, analysis.viability_score, tags, analysis.summary | LIMIT 20",
    "params": {
      "tag_pattern": {
        "type": "string",
        "description": "Tag pattern to search for (use wildcards like '*ai-agents*')"
      },
      "min_viability": {
        "type": "float",
        "description": "Minimum viability score filter (0-100, default 0)"
      }
    }
  }
}
```

---

### 5. Get Cached Search Results — REMOVED (moved to Redis)

**Removed.** Ephemeral web-search caching moved from the `web-search-cache` Elasticsearch index to Redis (`tools/cache.py`, key `search:<hash>`). This ES|QL tool and its backing index no longer exist. Do **not** create it.

---

### 6. Get Cached GitHub Metrics — REMOVED (moved to Redis)

**Removed.** Ephemeral GitHub-metrics caching moved from the `github-metrics-cache` Elasticsearch index to Redis (`tools/cache.py`, key `gh-metrics:<repo>`). This ES|QL tool and its backing index no longer exist. Do **not** create it.

> Note: "Get Cached Report" (#10, `get-cached-report`) is **not** affected — it reads the persistent `research-reports` index, not an ephemeral cache, and stays in Elasticsearch.

---

### 7. Get Repository Time Series

**Original Function:** `get_repo_timeseries()` (line 656)

**Purpose:** Retrieve time-series metrics data for trend visualization.

**Dev Tools Command:**

```json
POST kbn:/api/agent_builder/tools
{
  "id": "get-repo-timeseries",
  "type": "esql",
  "description": "Retrieve time-series metrics data for a repository. Use for building trend visualizations and analyzing metric changes over time.",
  "tags": ["timeseries", "metrics", "analytics"],
  "configuration": {
    "query": "FROM repo-timeseries | WHERE repo == ?repo_name AND timestamp >= ?start_date | SORT timestamp ASC | KEEP repo, timestamp, stars, forks, open_issues, commits_week, commits_month, issue_close_rate, pr_merge_rate | LIMIT 1000",
    "params": {
      "repo_name": {
        "type": "string",
        "description": "Full repository name (e.g., 'langchain-ai/deepagents')"
      },
      "start_date": {
        "type": "date",
        "description": "Start date for time series in ISO format"
      }
    }
  }
}
```

**Aggregated Stats Tool:**

```json
POST kbn:/api/agent_builder/tools
{
  "id": "get-repo-timeseries-stats",
  "type": "esql",
  "description": "Get aggregated statistics for a repository's time-series data including averages and ranges.",
  "tags": ["timeseries", "stats", "analytics"],
  "configuration": {
    "query": "FROM repo-timeseries | WHERE repo == ?repo_name AND timestamp >= ?start_date | STATS avg_stars = AVG(stars), max_stars = MAX(stars), min_stars = MIN(stars), avg_commits_week = AVG(commits_week), snapshot_count = COUNT(*) BY repo",
    "params": {
      "repo_name": {
        "type": "string",
        "description": "Full repository name"
      },
      "start_date": {
        "type": "date",
        "description": "Start date for analysis in ISO format"
      }
    }
  }
}
```

---

### 8. Get Adoption Signals

**Original Function:** `get_adoption_signals()` (line 748)

**Purpose:** Retrieve adoption signals (blog posts, case studies, job postings) for a repository.

**Dev Tools Command:**

```json
POST kbn:/api/agent_builder/tools
{
  "id": "get-adoption-signals",
  "type": "esql",
  "description": "Retrieve adoption signals like blog posts, case studies, and job postings for a repository.",
  "tags": ["adoption", "signals", "web-research"],
  "configuration": {
    "query": "FROM adoption-signals | WHERE repo == ?repo_name AND timestamp >= ?start_date | SORT timestamp DESC | KEEP repo, timestamp, signal_type, source_url, source_title, company_mentioned, sentiment, snippet | LIMIT 100",
    "params": {
      "repo_name": {
        "type": "string",
        "description": "Full repository name"
      },
      "start_date": {
        "type": "date",
        "description": "Start date for history in ISO format"
      }
    }
  }
}
```

**Filtered by Signal Type:**

```json
POST kbn:/api/agent_builder/tools
{
  "id": "get-adoption-signals-by-type",
  "type": "esql",
  "description": "Retrieve adoption signals filtered by type (blog_post, case_study, conference_talk, job_posting).",
  "tags": ["adoption", "signals", "filtered"],
  "configuration": {
    "query": "FROM adoption-signals | WHERE repo == ?repo_name AND signal_type == ?signal_type AND timestamp >= ?start_date | SORT timestamp DESC | KEEP repo, timestamp, signal_type, source_title, source_url, company_mentioned, sentiment, snippet | LIMIT 50",
    "params": {
      "repo_name": {
        "type": "string",
        "description": "Full repository name"
      },
      "signal_type": {
        "type": "string",
        "description": "Signal type: blog_post, case_study, conference_talk, or job_posting"
      },
      "start_date": {
        "type": "date",
        "description": "Start date for history in ISO format"
      }
    }
  }
}
```

**Aggregated Signal Counts:**

```json
POST kbn:/api/agent_builder/tools
{
  "id": "count-adoption-signals",
  "type": "esql",
  "description": "Count adoption signals by type for a repository.",
  "tags": ["adoption", "stats", "aggregation"],
  "configuration": {
    "query": "FROM adoption-signals | WHERE repo == ?repo_name AND timestamp >= ?start_date | STATS count = COUNT(*) BY signal_type | SORT count DESC",
    "params": {
      "repo_name": {
        "type": "string",
        "description": "Full repository name"
      },
      "start_date": {
        "type": "date",
        "description": "Start date for history in ISO format"
      }
    }
  }
}
```

---

### 9. Get Latest Research Report

**Original Function:** `get_latest_report()` (line 854)

**Purpose:** Get the most recent research report for a repository.

**Dev Tools Command:**

```json
POST kbn:/api/agent_builder/tools
{
  "id": "get-latest-report",
  "type": "esql",
  "description": "Get the most recent research report for a repository including scores, recommendation, and full report content.",
  "tags": ["reports", "research", "latest"],
  "configuration": {
    "query": "FROM research-reports | WHERE repo == ?repo_name | SORT timestamp DESC | KEEP repo, timestamp, report_type, viability_score, recommendation, risk_flags, summary, full_report | LIMIT 1",
    "params": {
      "repo_name": {
        "type": "string",
        "description": "Full repository name"
      }
    }
  }
}
```

---

### 10. Get Cached Report

**Original Function:** `get_cached_report()` (line 880)

**Purpose:** Get a recent research report if available (within max age).

**Dev Tools Command:**

```json
POST kbn:/api/agent_builder/tools
{
  "id": "get-cached-report",
  "type": "esql",
  "description": "Get a cached research report if one exists within the specified age limit. Use for cost savings before running new evaluations.",
  "tags": ["reports", "cache", "research"],
  "configuration": {
    "query": "FROM research-reports | WHERE repo == ?repo_name AND timestamp >= ?min_timestamp | SORT timestamp DESC | KEEP repo, timestamp, report_type, viability_score, health_score, community_score, adoption_score, recommendation, summary | LIMIT 1",
    "params": {
      "repo_name": {
        "type": "string",
        "description": "Full repository name"
      },
      "min_timestamp": {
        "type": "date",
        "description": "Minimum timestamp for cache validity in ISO format"
      }
    }
  }
}
```

---

### 11. Get Past Discoveries

**Original Function:** `get_past_discoveries()` (line 965)

**Purpose:** Get past technology discovery results.

**Note:** The `technologies` field is a nested object. Access sub-fields like `technologies.name`, `technologies.github_url`, `technologies.stars`, etc.

**Dev Tools Command (all discoveries):**

```json
POST kbn:/api/agent_builder/tools
{
  "id": "get-past-discoveries",
  "type": "esql",
  "description": "Retrieve past technology discovery results within a time range.",
  "tags": ["discoveries", "history", "research"],
  "configuration": {
    "query": "FROM technology-discoveries | WHERE timestamp >= ?start_date | SORT timestamp DESC | KEEP timestamp, use_case, technology_count, technologies.name, technologies.github_url, technologies.stars, technologies.description | LIMIT 50",
    "params": {
      "start_date": {
        "type": "date",
        "description": "Start date for history in ISO format"
      }
    }
  }
}
```

**Filtered by Use Case:**

```json
POST kbn:/api/agent_builder/tools
{
  "id": "search-discoveries-by-use-case",
  "type": "esql",
  "description": "Search past technology discoveries by use case description.",
  "tags": ["discoveries", "search", "use-case"],
  "configuration": {
    "query": "FROM technology-discoveries | WHERE use_case LIKE ?use_case_pattern AND timestamp >= ?start_date | SORT timestamp DESC | KEEP timestamp, use_case, technology_count, technologies.name, technologies.github_url, technologies.stars | LIMIT 20",
    "params": {
      "use_case_pattern": {
        "type": "string",
        "description": "Use case pattern to search for (use wildcards like '*AI agents*')"
      },
      "start_date": {
        "type": "date",
        "description": "Start date for history in ISO format"
      }
    }
  }
}
```

---

### 12. Get All Discovered Repos

**Original Function:** `get_all_discovered_repos()` (line 1005)

**Purpose:** Get all unique repositories from past discoveries.

**Dev Tools Command:**

```json
POST kbn:/api/agent_builder/tools
{
  "id": "get-all-discovered-repos",
  "type": "esql",
  "description": "Get all discovered technology repositories with their GitHub URLs and star counts.",
  "tags": ["discoveries", "repos", "all"],
  "configuration": {
    "query": "FROM technology-discoveries | KEEP timestamp, use_case, technologies.name, technologies.github_url, technologies.stars | SORT timestamp DESC | LIMIT 1000",
    "params": {}
  }
}
```

---

## Indices Reference

| Index                    | Purpose                                      |
| ------------------------ | -------------------------------------------- |
| `technology-research`    | Main research snapshots with embeddings      |
| `repo-timeseries`        | Point-in-time metrics for trend graphs       |
| `commit-history`         | Weekly commit aggregates by author           |
| `adoption-signals`       | Structured web findings                      |
| `research-reports`       | Final evaluation/comparison reports          |
| `technology-discoveries` | Discovered technologies by use case          |

> The former `web-search-cache`, `github-metrics-cache`, and `github-data-cache` indices were removed; ephemeral caching now lives in Redis (`tools/cache.py`).

---

## Bulk Tool Creation Script

Run all tool creations in Dev Tools Console.

**Note:** ES|QL parameters cannot be used in date math expressions. All date parameters must be passed as ISO format strings (e.g., `2024-10-01T00:00:00Z`).

```bash
# 1. Find Similar Technologies
POST kbn:/api/agent_builder/tools
{"id":"find-similar-technologies","type":"esql","description":"Use semantic search to find technologies similar to a given description.","tags":["search","semantic","technology-research"],"configuration":{"query":"FROM technology-research METADATA _score | WHERE semantic_content:?description | SORT _score DESC | KEEP repo, timestamp, tags, analysis.viability_score, analysis.summary, _score | LIMIT ?limit","params":{"description":{"type":"string","description":"Natural language description of the technology or use case"},"limit":{"type":"integer","description":"Maximum results (default 5)"}}}}

# 2. Get Trend Data
POST kbn:/api/agent_builder/tools
{"id":"get-trend-data","type":"esql","description":"Retrieve historical snapshots for trend analysis.","tags":["trends","analytics"],"configuration":{"query":"FROM technology-research | WHERE repo == ?repo_name AND timestamp >= ?start_date | SORT timestamp ASC | KEEP repo, timestamp, metrics.stars, metrics.open_issues, analysis.viability_score | LIMIT 100","params":{"repo_name":{"type":"string","description":"Full repository name"},"start_date":{"type":"date","description":"Start date in ISO format"}}}}

# 3. Get Latest Snapshot (for comparisons)
POST kbn:/api/agent_builder/tools
{"id":"get-latest-snapshot","type":"esql","description":"Get the most recent research snapshot for a repository.","tags":["comparison","snapshot"],"configuration":{"query":"FROM technology-research | WHERE repo == ?repo_name | SORT timestamp DESC | KEEP repo, timestamp, metrics.stars, metrics.forks, metrics.open_issues, metrics.contributors, analysis.viability_score, analysis.risk_flags | LIMIT 1","params":{"repo_name":{"type":"string","description":"Full repository name"}}}}

# 4. Search by Tags
POST kbn:/api/agent_builder/tools
{"id":"search-by-tags","type":"esql","description":"Search technologies by tags with viability filter.","tags":["search","tags"],"configuration":{"query":"FROM technology-research | WHERE tags LIKE ?tag_pattern AND analysis.viability_score >= ?min_viability | SORT analysis.viability_score DESC, timestamp DESC | KEEP repo, analysis.viability_score, tags, analysis.summary | LIMIT 20","params":{"tag_pattern":{"type":"string","description":"Tag pattern (use wildcards)"},"min_viability":{"type":"float","description":"Minimum viability score (0-100)"}}}}

# 5. Get Cached Search — REMOVED (ephemeral caching moved to Redis, tools/cache.py)
# 6. Get Cached GitHub Metrics — REMOVED (ephemeral caching moved to Redis, tools/cache.py)

# 7. Get Repo Time Series
POST kbn:/api/agent_builder/tools
{"id":"get-repo-timeseries","type":"esql","description":"Retrieve time-series metrics for trend visualization.","tags":["timeseries","metrics"],"configuration":{"query":"FROM repo-timeseries | WHERE repo == ?repo_name AND timestamp >= ?start_date | SORT timestamp ASC | KEEP repo, timestamp, stars, forks, open_issues, commits_week, commits_month, issue_close_rate, pr_merge_rate | LIMIT 1000","params":{"repo_name":{"type":"string","description":"Full repository name"},"start_date":{"type":"date","description":"Start date in ISO format"}}}}

# 8. Get Adoption Signals
POST kbn:/api/agent_builder/tools
{"id":"get-adoption-signals","type":"esql","description":"Retrieve adoption signals for a repository.","tags":["adoption","signals"],"configuration":{"query":"FROM adoption-signals | WHERE repo == ?repo_name AND timestamp >= ?start_date | SORT timestamp DESC | KEEP repo, timestamp, signal_type, source_url, source_title, company_mentioned, sentiment, snippet | LIMIT 100","params":{"repo_name":{"type":"string","description":"Full repository name"},"start_date":{"type":"date","description":"Start date in ISO format"}}}}

# 9. Get Latest Report
POST kbn:/api/agent_builder/tools
{"id":"get-latest-report","type":"esql","description":"Get the most recent research report for a repository.","tags":["reports","research"],"configuration":{"query":"FROM research-reports | WHERE repo == ?repo_name | SORT timestamp DESC | KEEP repo, timestamp, report_type, viability_score, recommendation, risk_flags, summary, full_report | LIMIT 1","params":{"repo_name":{"type":"string","description":"Full repository name"}}}}

# 10. Get Cached Report
POST kbn:/api/agent_builder/tools
{"id":"get-cached-report","type":"esql","description":"Get a cached research report within age limit.","tags":["reports","cache"],"configuration":{"query":"FROM research-reports | WHERE repo == ?repo_name AND timestamp >= ?min_timestamp | SORT timestamp DESC | KEEP repo, timestamp, report_type, viability_score, health_score, community_score, adoption_score, recommendation, summary | LIMIT 1","params":{"repo_name":{"type":"string","description":"Full repository name"},"min_timestamp":{"type":"date","description":"Minimum timestamp in ISO format"}}}}

# 11. Get Past Discoveries (note: technologies is nested, use sub-fields)
POST kbn:/api/agent_builder/tools
{"id":"get-past-discoveries","type":"esql","description":"Retrieve past technology discovery results.","tags":["discoveries","history"],"configuration":{"query":"FROM technology-discoveries | WHERE timestamp >= ?start_date | SORT timestamp DESC | KEEP timestamp, use_case, technology_count, technologies.name, technologies.github_url, technologies.stars, technologies.description | LIMIT 50","params":{"start_date":{"type":"date","description":"Start date in ISO format"}}}}

# 12. Search Discoveries by Use Case
POST kbn:/api/agent_builder/tools
{"id":"search-discoveries-by-use-case","type":"esql","description":"Search past discoveries by use case.","tags":["discoveries","search"],"configuration":{"query":"FROM technology-discoveries | WHERE use_case LIKE ?use_case_pattern AND timestamp >= ?start_date | SORT timestamp DESC | KEEP timestamp, use_case, technology_count, technologies.name, technologies.github_url, technologies.stars | LIMIT 20","params":{"use_case_pattern":{"type":"string","description":"Use case pattern (use wildcards)"},"start_date":{"type":"date","description":"Start date in ISO format"}}}}

# 13. Count Adoption Signals
POST kbn:/api/agent_builder/tools
{"id":"count-adoption-signals","type":"esql","description":"Count adoption signals by type for a repository.","tags":["adoption","stats"],"configuration":{"query":"FROM adoption-signals | WHERE repo == ?repo_name AND timestamp >= ?start_date | STATS count = COUNT(*) BY signal_type | SORT count DESC","params":{"repo_name":{"type":"string","description":"Full repository name"},"start_date":{"type":"date","description":"Start date in ISO format"}}}}

# 14. Get Repo Time Series Stats
POST kbn:/api/agent_builder/tools
{"id":"get-repo-timeseries-stats","type":"esql","description":"Get aggregated statistics for repository time-series data.","tags":["timeseries","stats"],"configuration":{"query":"FROM repo-timeseries | WHERE repo == ?repo_name AND timestamp >= ?start_date | STATS avg_stars = AVG(stars), max_stars = MAX(stars), min_stars = MIN(stars), avg_commits_week = AVG(commits_week), snapshot_count = COUNT(*) BY repo","params":{"repo_name":{"type":"string","description":"Full repository name"},"start_date":{"type":"date","description":"Start date in ISO format"}}}}

# 15. Get Adoption Signals by Type (note: no use_case field in adoption-signals)
POST kbn:/api/agent_builder/tools
{"id":"get-adoption-signals-by-type","type":"esql","description":"Retrieve adoption signals filtered by type.","tags":["adoption","signals","filtered"],"configuration":{"query":"FROM adoption-signals | WHERE repo == ?repo_name AND signal_type == ?signal_type AND timestamp >= ?start_date | SORT timestamp DESC | KEEP repo, timestamp, signal_type, source_title, source_url, company_mentioned, sentiment, snippet | LIMIT 50","params":{"repo_name":{"type":"string","description":"Full repository name"},"signal_type":{"type":"string","description":"Signal type: blog_post, case_study, conference_talk, job_posting"},"start_date":{"type":"date","description":"Start date in ISO format"}}}}

# 16. Get All Discovered Repos
POST kbn:/api/agent_builder/tools
{"id":"get-all-discovered-repos","type":"esql","description":"Get all discovered technology repositories.","tags":["discoveries","repos","all"],"configuration":{"query":"FROM technology-discoveries | KEEP timestamp, use_case, technologies.name, technologies.github_url, technologies.stars | SORT timestamp DESC | LIMIT 1000","params":{}}}
```

---

## Usage Notes

1. **Semantic Search Syntax:** Two options available:
   - Match operator: `semantic_content:"query text"`
   - Match function: `match(semantic_content, "query text")`

2. **METADATA Declaration:** Include `METADATA _score` to calculate relevance scores for semantic search.

3. **Parameters:** Use `?parameter_name` syntax. The agent interpolates values at runtime.

4. **LIMIT Clauses:** Always include to prevent excessive result sets.

5. **Hybrid Search:** Combine semantic and lexical with boost weights: `{"boost": 0.75}`

6. **Date Parameters:** ES|QL parameters **cannot** be used within date math expressions like `NOW() - ?days days`. Instead, pass complete ISO date strings (e.g., `2024-10-01T00:00:00Z`) as the parameter value. The calling code should compute the date before invoking the tool.

7. **Date Math in Static Queries:** Date math like `NOW() - 90 days` works in static queries but not with parameterized values.

8. **Disabled Object Fields:** Some indices have fields mapped with `"enabled": false`. These fields are stored but cannot be queried with KEEP. Use the document API to retrieve full documents when needed.

9. **Nested Object Fields:** For indices with nested objects (e.g., `technologies` in technology-discoveries), access sub-fields using dot notation: `technologies.name`, `technologies.github_url`, etc.
