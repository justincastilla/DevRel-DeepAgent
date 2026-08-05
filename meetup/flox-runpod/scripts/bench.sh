#!/usr/bin/env bash
# Tokens/sec against any OpenAI-compatible endpoint. Run it on the laptop, then
# on the RunPod pod. The two numbers are the demo.
#
#   ./bench.sh                                              # localhost:8080
#   ./bench.sh https://<pod-id>-8080.proxy.runpod.net/v1    # the pod
#
# Wall-clock measurement on purpose: it includes queueing and network, which is
# what the audience actually experiences.

set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8080/v1}"
PROMPT="${PROMPT:-Explain what a reproducible development environment is, in three sentences.}"
MAX_TOKENS="${MAX_TOKENS:-200}"
RUNS="${RUNS:-3}"

for cmd in curl jq; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "need $cmd" >&2; exit 1; }
done

payload=$(jq -n --arg p "$PROMPT" --argjson m "$MAX_TOKENS" '{
  model: "local",
  messages: [{role: "user", content: $p}],
  max_tokens: $m,
  stream: false
}')

echo "endpoint: $BASE_URL"
echo "runs:     $RUNS  (first is a warmup, excluded)"
echo

total=0
counted=0

for i in $(seq 0 "$RUNS"); do
  start=$(date +%s.%N)
  resp=$(curl -sS --fail-with-body -m 300 \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer ${LLAMACPP_API_KEY:-none}" \
    -d "$payload" "${BASE_URL}/chat/completions")
  end=$(date +%s.%N)

  tokens=$(printf '%s' "$resp" | jq -r '.usage.completion_tokens // 0')
  elapsed=$(echo "$end - $start" | bc)

  if [ "$tokens" -eq 0 ]; then
    echo "no completion_tokens in response:" >&2
    printf '%s\n' "$resp" | head -c 500 >&2
    exit 1
  fi

  tps=$(echo "scale=2; $tokens / $elapsed" | bc)

  if [ "$i" -eq 0 ]; then
    printf 'warmup   %6s tok in %5ss  ->  %8s tok/s\n' "$tokens" "$(printf '%.2f' "$elapsed")" "$tps"
  else
    printf 'run %-2s   %6s tok in %5ss  ->  %8s tok/s\n' "$i" "$tokens" "$(printf '%.2f' "$elapsed")" "$tps"
    total=$(echo "$total + $tps" | bc)
    counted=$((counted + 1))
  fi
done

echo
printf 'MEAN: %s tok/s\n' "$(echo "scale=2; $total / $counted" | bc)"
