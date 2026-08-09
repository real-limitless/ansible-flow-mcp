#!/usr/bin/env bash
# Interactive hub operator TUI inside the lab hub container (needs TTY).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
  COMPOSE=(podman compose)
elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
else
  COMPOSE=(docker compose)
fi

exec "${COMPOSE[@]}" -f docker-compose.yml exec -it \
  -e ANSIBLE_FLOW_HUB_DIR=/var/lib/ansible-flow/hub \
  -e ANSIBLE_FLOW_ROLE=hub \
  hub ansible-flow-mcp tui
