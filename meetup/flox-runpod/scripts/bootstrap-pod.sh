#!/usr/bin/env bash
# Install Flox on a fresh RunPod pod. Paste into the pod's web terminal.
#
#   curl -fsSL https://raw.githubusercontent.com/<you>/<repo>/main/meetup/flox-runpod/scripts/bootstrap-pod.sh | bash
#
# Then:
#   flox activate -r <you>/<env-name> --start-services
#
# Rehearse this on your exact base image. RunPod's default containers run as
# root so apt works, but Flox writes to /nix -- confirm that before stage.

set -euo pipefail

FLOX_VERSION="${FLOX_VERSION:-1.14.0}"

case "$(uname -m)" in
  x86_64)          ARCH="x86_64-linux" ;;
  aarch64 | arm64) ARCH="aarch64-linux" ;;
  *) echo "unsupported arch: $(uname -m)" >&2; exit 1 ;;
esac

if command -v flox >/dev/null 2>&1; then
  echo "flox already installed: $(flox --version)"
  exit 0
fi

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

echo "==> installing prerequisites"
$SUDO apt-get update -qq
$SUDO apt-get install -y -qq curl ca-certificates

DEB="/tmp/flox-${FLOX_VERSION}.${ARCH}.deb"
echo "==> downloading flox ${FLOX_VERSION} (${ARCH})"
curl -fsSL --retry 3 -o "$DEB" \
  "https://downloads.flox.dev/by-env/stable/deb/flox-${FLOX_VERSION}.${ARCH}.deb"

echo "==> installing flox"
$SUDO apt-get install -y "$DEB"
rm -f "$DEB"

flox --version

cat <<'EOF'

Flox is installed. Next:

  flox auth login                                   # if the env is private
  flox activate -r <you>/<env-name> --start-services

GPU check (the driver comes from the pod, the toolkit from Flox):

  nvidia-smi --query-gpu=name,memory.total --format=csv

EOF
