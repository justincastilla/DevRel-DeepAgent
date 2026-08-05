# Demo 3: point DevRel-DeepAgent at the RunPod pod

llama.cpp's server is OpenAI-compatible, and `agent.py` already builds a
`ChatOpenAI` with a custom `base_url` for the Azure path. So backing this agent
with a self-hosted model on a rented GPU is a base-URL change, not a rewrite —
which is the point you're making on stage.

## The change

In `agent.py`, add a model key:

```python
MODELS = {
    "claude": "anthropic:claude-sonnet-4-5-20250929",
    "gpt": "azure:gpt-5.4",
    "local": "openai:local",          # llama.cpp on a RunPod pod
}
```

and a branch alongside the existing `elif model_key == "gpt"`:

```python
elif model_key == "local":
    from langchain_openai import ChatOpenAI

    model_instance = ChatOpenAI(
        base_url=os.getenv("RUNPOD_LLM_URL", "http://127.0.0.1:8080/v1"),
        api_key=os.getenv("RUNPOD_LLM_API_KEY", "not-needed"),
        model="local",
        temperature=0.2,
        max_tokens=4096,
    )
```

`_validate_config()` requires `ANTHROPIC_API_KEY`; either export a dummy value or
skip that check when `model_key == "local"`.

## Running it

```bash
export RUNPOD_LLM_URL="https://<pod-id>-8080.proxy.runpod.net/v1"
python cli.py ask "Compare vLLM and llama.cpp for self-hosted inference" --verbose --model local
```

(If `cli.py` doesn't accept `--model` for `ask`, call `get_agent("local")` from a
short script instead — for the demo, either is fine.)

## What to say while it runs

- **Nothing about the agent changed.** Four subagents, the same tools, the same
  Elasticsearch. Only the endpoint moved.
- **Two boundaries held at once.** Flox kept the environment contract (the same
  manifest ran on a Mac and an H100); RunPod kept the API contract (a URL that
  speaks OpenAI). Neither had to know about the other.
- **Then kill the pod.** The environment is still in FloxHub. The GPU bill
  stopped. Durable environment, disposable compute — that's the whole talk.

## Caveats worth naming honestly

A 4B-parameter local model will not orchestrate four subagents as well as a
frontier model, and a meetup audience will notice. Two ways to handle it:

1. **Lean into it.** Show the local run producing a rougher report next to the
   Claude run. The demo is the *plumbing*, and admitting the quality gap buys you
   credibility for everything else you said.
2. **Narrow the task.** Give the local model one subagent's job — summarize a
   single repo's sentiment — where a small model does fine, and note that this is
   the realistic use for self-hosted inference: high-volume, narrow, cost-sensitive
   work, with the frontier model kept for orchestration.

Option 2 demos better. Option 1 is more memorable.
