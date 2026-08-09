#!/usr/bin/env bash
# Stdio MCP bridge: run hub session inside the lab hub container.
# Use this from the HOST so OpenCode talks to the compose hub inventory.
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

# Fail fast if hub is down
if ! "${COMPOSE[@]}" -f docker-compose.yml ps -q hub 2>/dev/null | grep -q .; then
  echo "hub container not running — cd test && ./scripts/up.sh && ./scripts/enroll.sh" >&2
  exit 1
fi

exec "${COMPOSE[@]}" -f docker-compose.yml exec -T \
  -e ANSIBLE_FLOW_HUB_DIR=/var/lib/ansible-flow/hub \
  -e ANSIBLE_FLOW_ROLE=hub \
  hub ansible-flow-mcp hub session
