# Quick Start Guide

Get the DevRel Research Agent up and running in 5 minutes.

## Prerequisites

- Python 3.12+
- pip package manager
- API keys (see below)

## Step 1: Install Dependencies

```bash
pip install -r requirements.txt
```

## Step 2: Setup Environment

Your `.env` file should already contain the required API keys:

- `ANTHROPIC_API_KEY` - For Claude AI
- `TAVILY_API_KEY` - For web search
- `GITHUB_API_KEY` - For GitHub API access
- `ELASTICSEARCH_HOST` - Your Elasticsearch cluster URL
- `ELASTICSEARCH_API_KEY` - Elasticsearch authentication
- `REDIS_URL` - Redis connection for caching (optional; defaults to `redis://localhost:6379/0`)
- `LANGSMITH_API_KEY` - For observability (optional)

Caching of external API results uses Redis. It is optional and degrades gracefully — if Redis is unavailable, every cache lookup is treated as a miss and the app still runs. Start a local Redis with:

```bash
docker run --rm -p 6379:6379 redis:7-alpine
```

(Or run `docker compose up`, which starts a `redis` service automatically.)

## Step 3: Setup Elasticsearch Index

```bash
python scripts/setup_elasticsearch.py
```

When prompted, choose whether to create or recreate the index.

## Step 4: Run Your First Query

**Option A: Using the CLI**
```bash
python cli.py evaluate langchain-ai/deepagents
```

**Option B: Using the agent directly**
```bash
python agent.py "Evaluate langchain-ai/deepagents"
```

## Common Tasks

### Evaluate a Technology

```bash
python cli.py evaluate fastapi/fastapi --use-case "building REST APIs"
```

### Compare Technologies

```bash
python cli.py compare fastapi/fastapi django/django pallets/flask
```

### Search Existing Research

```bash
python cli.py search "Python web frameworks" --tags python backend
```

### Export Results

```bash
python cli.py evaluate facebook/react --output report.md --format markdown
```

## Tracking All Repositories

The `repositories.txt` file contains 80 repositories across 8 categories.

To research all of them (future feature):
```bash
# Coming soon
python cli.py batch repositories.txt --output results/
```

## Troubleshooting

### "Connection refused" from Elasticsearch
- Verify `ELASTICSEARCH_HOST` is correct
- Test connection: `curl -H "Authorization: ApiKey $ELASTICSEARCH_API_KEY" $ELASTICSEARCH_HOST`

### "GitHub API rate limit exceeded"
- Ensure `GITHUB_API_KEY` is set
- Authenticated requests have much higher rate limits (5000/hour vs 60/hour)

### "Tavily API error"
- Verify `TAVILY_API_KEY` is valid
- Check your API quota at https://tavily.com

### "Module not found" errors
- Ensure you're in the project directory
- Verify all dependencies installed: `pip list | grep deepagents`

## What's Next?

1. **Run the test suite** to see the agent in action:
   ```bash
   python scripts/test_agent.py
   ```

2. **Start tracking repositories** from `repositories.txt`

3. **Set up scheduled runs** (coming soon)

4. **Integrate with your workflow** using the Python API

## Need Help?

- Check logs: `tail -f devrel_research.log`
- Review examples in `scripts/test_agent.py`
- Read the full README.md for detailed documentation
