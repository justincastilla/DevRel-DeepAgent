"""
Setup script for Elasticsearch index.
Run once to create the index with proper mappings.
"""

import sys
from pathlib import Path

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from elasticsearch import Elasticsearch
from dotenv import load_dotenv

from config import config
from utils.logging_utils import setup_logging, get_logger

# Setup logging
setup_logging()
logger = get_logger(__name__)

# Load environment variables
load_dotenv()

INDICES = {
    "technology-research": {
    "mappings": {
        "properties": {
            "repo": {
                "type": "keyword"
            },
            "timestamp": {
                "type": "date"
            },
            "tags": {
                "type": "keyword"
            },
            "metrics": {
                "properties": {
                    "stars": {"type": "integer"},
                    "forks": {"type": "integer"},
                    "open_issues": {"type": "integer"},
                    "closed_issues": {"type": "integer"},
                    "open_prs": {"type": "integer"},
                    "merged_prs": {"type": "integer"},
                    "contributors": {"type": "integer"},
                }
            },
            "derived": {
                "properties": {
                    "repo_age_days": {"type": "integer"},
                    "stars_per_month": {"type": "float"},
                    "commits_30d": {"type": "integer"},
                    "commits_90d": {"type": "integer"},
                    "unique_authors_30d": {"type": "integer"},
                    "issue_close_rate": {"type": "float"},
                }
            },
            "analysis": {
                "properties": {
                    "viability_score": {"type": "float"},
                    "health_score": {"type": "float"},
                    "community_score": {"type": "float"},
                    "adoption_score": {"type": "float"},
                    "sentiment_score": {"type": "float"},
                    "risk_flags": {"type": "keyword"},
                    "recommendation": {"type": "keyword"},
                    "summary": {"type": "text"},
                    "recommendation_details": {
                        "properties": {
                            "use_if": {"type": "keyword"},
                            "avoid_if": {"type": "keyword"},
                        }
                    },
                }
            },
            "semantic_content": {
                "type": "semantic_text",
                "inference_id": "devrel-elser-endpoint"
            }
        }
        },
    },
    "web-search-cache": {
        "mappings": {
            "properties": {
                "query": {"type": "text"},
                "query_hash": {"type": "keyword"},
                "timestamp": {"type": "date"},
                "results": {"type": "object", "enabled": False},  # Store raw JSON without indexing
                "result_count": {"type": "integer"},
                "search_type": {"type": "keyword"},  # e.g., "tavily", "github_issues"
            }
        },
    },
    "github-metrics-cache": {
        "mappings": {
            "properties": {
                "repo": {"type": "keyword"},
                "timestamp": {"type": "date"},
                "metrics": {"type": "object", "enabled": False},  # Raw metrics JSON
                "derived": {"type": "object", "enabled": False},  # Derived calculations
            }
        },
    },
    "repo-timeseries": {
        "mappings": {
            "properties": {
                "repo": {"type": "keyword"},
                "timestamp": {"type": "date"},
                # Point-in-time metrics for graphing
                "stars": {"type": "integer"},
                "forks": {"type": "integer"},
                "open_issues": {"type": "integer"},
                "closed_issues": {"type": "integer"},
                "contributors": {"type": "integer"},
                "open_prs": {"type": "integer"},
                "merged_prs": {"type": "integer"},
                # Commit activity buckets (weekly aggregates from commit history)
                "commits_week": {"type": "integer"},  # Commits in the past week
                "commits_month": {"type": "integer"},  # Commits in the past month
                "unique_authors_week": {"type": "integer"},
                "unique_authors_month": {"type": "integer"},
                # Derived velocity metrics
                "issue_close_rate": {"type": "float"},
                "pr_merge_rate": {"type": "float"},
                "stars_per_month": {"type": "float"},
            }
        },
    },
    "commit-history": {
        "mappings": {
            "properties": {
                "repo": {"type": "keyword"},
                "captured_at": {"type": "date"},  # When we captured this data
                "commit_date": {"type": "date"},  # When the commit was made
                "week_bucket": {"type": "keyword"},  # e.g., "2024-W01" for aggregation
                "author": {"type": "keyword"},
                "commit_count": {"type": "integer"},  # For pre-aggregated weekly data
            }
        },
    },
    "adoption-signals": {
        "mappings": {
            "properties": {
                "repo": {"type": "keyword"},
                "timestamp": {"type": "date"},
                "signal_type": {"type": "keyword"},  # blog_post, case_study, conference_talk, job_posting
                # Source info
                "source_url": {"type": "keyword"},
                "source_title": {"type": "text"},
                "source_domain": {"type": "keyword"},
                "source_date": {"type": "date"},
                # Extracted data
                "company_mentioned": {"type": "keyword"},  # For case studies
                "use_case": {"type": "text"},
                "sentiment": {"type": "keyword"},  # positive, neutral, negative
                "snippet": {"type": "text"},  # Relevant excerpt
                # Search metadata
                "search_query": {"type": "text"},
                "relevance_score": {"type": "float"},
            }
        },
    },
    "research-reports": {
        "mappings": {
            "properties": {
                "repo": {"type": "keyword"},
                "timestamp": {"type": "date"},
                "report_type": {"type": "keyword"},  # evaluation, comparison
                "use_case": {"type": "text"},
                # Scores
                "viability_score": {"type": "float"},
                "health_score": {"type": "float"},
                "community_score": {"type": "float"},
                "adoption_score": {"type": "float"},
                # Recommendation
                "recommendation": {"type": "keyword"},  # COVER, WATCH, SKIP
                "risk_flags": {"type": "keyword"},
                "strengths": {"type": "text"},
                "concerns": {"type": "text"},
                # Full report for retrieval
                "full_report": {"type": "text"},
                "summary": {"type": "text"},
                # For comparisons
                "compared_repos": {"type": "keyword"},
            }
        },
    },
    "technology-discoveries": {
        "mappings": {
            "properties": {
                "timestamp": {"type": "date"},
                "use_case": {"type": "text"},
                "use_case_keyword": {"type": "keyword"},
                # Discovered technologies
                "technologies": {
                    "type": "nested",
                    "properties": {
                        "name": {"type": "keyword"},
                        "github_url": {"type": "keyword"},
                        "website_url": {"type": "keyword"},
                        "description": {"type": "text"},
                        "relevance": {"type": "text"},
                        "stars": {"type": "integer"},
                    }
                },
                "technology_count": {"type": "integer"},
                # Recommendations from discovery
                "most_promising": {"type": "keyword"},
                "full_report": {"type": "text"},
            }
        },
    },
}


def setup_index(es, index_name: str, mapping: dict):
    """Create a single index."""
    if es.indices.exists(index=index_name):
        print(f"Index '{index_name}' already exists.")
        response = input(f"Delete and recreate '{index_name}'? (y/N): ")
        if response.lower() == 'y':
            es.indices.delete(index=index_name)
            logger.info(f"Deleted existing index '{index_name}'")
            print(f"Deleted index '{index_name}'")
        else:
            print(f"Skipping '{index_name}'.")
            logger.info(f"User chose to skip index '{index_name}'")
            return False

    es.indices.create(index=index_name, body=mapping)
    logger.info(f"Created index '{index_name}' with mappings")
    print(f"✓ Created index '{index_name}'")
    return True


def setup_all_indices():
    """Create or update all indices."""
    logger.info("Starting Elasticsearch index setup")

    if not config.ELASTICSEARCH_URL or not config.ELASTICSEARCH_API_KEY:
        logger.error("Elasticsearch credentials not configured")
        print("Error: ELASTICSEARCH_URL and ELASTICSEARCH_API_KEY must be set in .env")
        sys.exit(1)

    try:
        es = Elasticsearch(
            config.ELASTICSEARCH_URL,
            api_key=config.ELASTICSEARCH_API_KEY,
        )

        # Test connection
        if not es.ping():
            logger.error("Cannot connect to Elasticsearch")
            print("Error: Cannot connect to Elasticsearch")
            sys.exit(1)

        logger.info("Connected to Elasticsearch successfully")
        print(f"\nSetting up {len(INDICES)} indices...\n")

        created = 0
        for index_name, mapping in INDICES.items():
            if setup_index(es, index_name, mapping):
                created += 1

        print(f"\n✓ Setup complete. {created} indices created/updated.")

    except Exception as e:
        logger.error(f"Failed to setup Elasticsearch indices: {e}")
        print(f"Error: Failed to setup indices: {e}")
        sys.exit(1)


if __name__ == "__main__":
    setup_all_indices()
