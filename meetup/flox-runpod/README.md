# Flox × RunPod: a Meetup Demo Runbook

**The one-sentence pitch:** Flox decides *what software* runs; RunPod decides *what
silicon* it runs on. Neither one solves the other's problem, which is exactly why
they compose — and the composition is a live demo you can do in 15 minutes.

---

## Why these two are a natural pair

| | Flox | RunPod |
|---|---|---|
| Solves | "works on my machine" | "I don't own an H100" |
| Unit of work | a declarative environment (`manifest.toml`) | an ephemeral GPU container |
| Lifetime | permanent, versioned, in FloxHub/git | minutes, billed by the minute |
| Weak spot | doesn't give you hardware | a blank box with a driver and nothing else |

A GPU pod is a *fast, expensive, empty* machine. Every minute spent
`pip install`-ing CUDA wheels on it is a minute you paid H100 rates for `apt`. Flox
turns that setup into one command that resolves from a lockfile — and the *same*
command works on the laptop you rehearsed on.

That inversion is the whole talk: **the environment is the durable artifact; the
GPU is disposable.**

---

## The three demos

Run them in this order. Demo 1 is the emotional beat, Demo 2 is the technical
payoff, Demo 3 makes it *your* demo rather than a vendor demo.

### Demo 1 — "Teleport": the same environment, different silicon

The audience watches one environment definition move from a laptop with no GPU to
a rented H100, unchanged.

**On your laptop (~2 min)**

```bash
git clone https://github.com/flox/llamacpp-flox-runtime && cd llamacpp-flox-runtime
flox activate --start-services
curl -s localhost:8080/health
# then a chat completion — note the tokens/sec out loud. It's slow. That's the point.
```

**Push it (~10 sec)**

```bash
flox push          # -> FloxHub as <you>/llamacpp-flox-runtime
```

**On a bare RunPod pod (~3 min)**

Deploy any CUDA base image (`runpod/pytorch:*` or plain `nvidia/cuda:12.9.0-base-ubuntu22.04`),
expose TCP 8080, then in the pod's web terminal:

```bash
nvidia-smi                     # the driver is here...
python -c "import torch"       # ...and nothing else is. Blank box.

./bootstrap-pod.sh             # installs flox (one .deb) — see scripts/
flox activate -r <you>/llamacpp-flox-runtime --start-services
```

Same command. Same manifest. Now hit `/v1/chat/completions` again and read the
tokens/sec. The delta *is* the demo — put both numbers on a slide.

**Why it actually works** (say this while the model loads):

- `[install]` entries carry a `.systems` constraint, so the manifest asks for the
  CUDA-built `llama-cpp` on `x86_64-linux` and gracefully does something else on
  your Mac. One manifest, two hardware targets.
- `[options] cuda-detection = true` lets the environment find the host's
  `libcuda.so.1` — the driver stays the pod's problem, the toolkit stays Flox's
  problem. That separation is why the *same* env can be CPU-only locally and
  GPU-accelerated remotely without an `if` statement anywhere.
- Nothing was built on the pod. It resolved from a lockfile.

### Demo 2 — "No Dockerfile": `flox containerize` → RunPod custom template

For the half of the room that will ask "why not just use Docker?"

```bash
flox containerize --tag meetup -f - | docker load
docker tag llamacpp-flox-runtime:meetup ghcr.io/<you>/meetup-llm:latest
docker push ghcr.io/<you>/meetup-llm:latest
```

Then deploy that image as a RunPod custom template. Same environment, third
delivery mechanism.

The slide that lands: your 12-line `manifest.toml` next to a real 60-line CUDA
`Dockerfile` full of `apt-get install --no-install-recommends` and pinned wheel
URLs. Then the punchline — **you never wrote a Dockerfile.** The OCI image is a
byproduct of the environment, and it's the same closure you've been running
locally all week, not a parallel definition that drifts.

This is also the honest answer to "Flox vs. containers": it's not vs. Flox is the
source of truth; the container is one output format. RunPod happily takes either
an image (Demo 2) or a pod you bootstrap (Demo 1).

### Demo 3 — "Vice versa": point *this* repo at the GPU

The first two demos show off Flox's portability using RunPod's hardware. This one
flips it: a real agent app running locally, whose brain is renting an H100 by the
minute.

`DevRel-DeepAgent` already has an OpenAI-compatible code path (`agent.py`,
`ChatOpenAI(base_url=...)`). llama.cpp's server speaks the same protocol, so the
pod you started in Demo 1 can back it directly:

```bash
export RUNPOD_LLM_URL="https://<pod-id>-8080.proxy.runpod.net/v1"
python cli.py ask "Compare vLLM and llama.cpp for self-hosted inference" --verbose --model local
```

See `agent-patch.md` in this directory for the ~15-line `MODELS` addition.

Two things to say while it streams:

1. The agent is unchanged. Swapping a frontier API for a self-hosted model is a
   base URL, because the environment (Flox) and the endpoint (RunPod) both kept
   their contracts.
2. Kill the pod at the end of the demo, live, on stage. The environment survives
   in FloxHub; the H100 bill stops. **That's the model** — durable environment,
   disposable compute.

---

## Files in this directory

| File | What it's for |
|---|---|
| `manifest.toml` | A self-contained GPU LLM env if you'd rather not use the upstream repo. Load with `flox init && flox edit -f manifest.toml`. |
| `scripts/bootstrap-pod.sh` | One-shot Flox install on a fresh pod. Paste-able into the RunPod web terminal. |
| `scripts/bench.sh` | Prints tokens/sec against an OpenAI-compatible endpoint. Run it on laptop and pod; the two numbers are your money slide. |
| `agent-patch.md` | Wiring DevRel-DeepAgent to a RunPod-hosted model. |

---

## Rehearsal notes — read this before you present

These are the things that actually break on stage.

**Model weights are the long pole, not the environment.** The default Phi-4-mini
Q8_0 is ~3.9 GB. On meetup wifi that's your whole slot. Fixes, in order of
preference:

1. Attach a **RunPod network volume**, download the model into it once the day
   before, and mount it on the demo pod. Set `LLAMACPP_MODELS_DIR` to the volume
   path. Restart is then seconds.
2. Start the pod and pre-pull during the intro slides, so it's warm at demo time.
3. Use a ~1 GB Q4 model. Less impressive tokens/sec, much safer.

**Have the pod already running.** RunPod GPU availability fluctuates; do not
gamble on an H100 being free at 7:15pm. Provision before you walk in and keep a
second pod on a different GPU type as backup. Per-minute billing means an
idle spare costs about the price of the pizza.

**Flox install on a pod needs root.** The `.deb` install uses `sudo`/`apt`;
RunPod's default containers run as root, so this works — but Flox wants to write
`/nix`, so verify on your exact base image during rehearsal, not on stage.
Some hardened or non-root images will fight you. If yours does, that's your cue
to fall back to Demo 2 (prebuilt image), which sidesteps the install entirely.

**`flox containerize` wants a container runtime** on the machine building it, or
use `-f -` / `-f ./out.tar` and load it elsewhere. Build and push the image
*before* the meetup; a registry push over conference wifi is not a demo.

**Have a fallback for the network.** Record a 60-second screen capture of the
tokens/sec comparison. If wifi dies you narrate over video instead of apologizing
for four minutes.

**Show the cost.** Open the RunPod billing page at the end with the actual dollar
figure for the demo — usually well under a dollar. A real number lands harder
than "it's cheap," and it reinforces the disposable-compute point.

---

## Talk structure (15 min)

| Time | Beat |
|---|---|
| 0–2 | The blank-GPU problem: you rented an H100 and it's `apt-get`ing |
| 2–6 | **Demo 1** — laptop → FloxHub → pod, same command, tokens/sec delta |
| 6–9 | How it works: `.systems`, `cuda-detection`, lockfile, driver/toolkit split |
| 9–12 | **Demo 2** — `flox containerize` → RunPod template; manifest vs. Dockerfile slide |
| 12–14 | **Demo 3** — the agent, backed by the pod |
| 14–15 | Kill the pod. Environment persists, bill stops. Show the receipt. |

**Closing line:** *"The GPU was rented. The environment was not."*

---

## Sources

- [flox containerize](https://flox.dev/docs/man/flox-containerize) · [manifest.toml reference](https://flox.dev/docs/man/manifest.toml.md) · [Sharing environments](https://flox.dev/docs/tutorials/sharing-environments) · [Install Flox](https://flox.dev/docs/install-flox/)
- [Flox + CUDA tutorial](https://flox.dev/docs/tutorials/cuda/) · [Reproducible NVIDIA CUDA stacks](https://flox.dev/blog/get-nvidia-cuda-stacks-that-travel-across-your-sdlc-with-flox/) · [flox/llamacpp-flox-runtime](https://github.com/flox/llamacpp-flox-runtime) · [flox/flox-cuda](https://github.com/flox/flox-cuda)
- [RunPod Pods overview](https://docs.runpod.io/pods/overview) · [Build a custom Pod template](https://docs.runpod.io/pods/templates/create-custom-template) · [Transfer files](https://docs.runpod.io/pods/storage/transfer-files) · [runpodctl](https://github.com/runpod/runpodctl)
