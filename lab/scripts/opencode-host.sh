#!/usr/bin/env bash
# Run OpenCode on the HOST attached to lab hub MCP (compose exec bridge).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v opencode >/dev/null 2>&1; then
  # common install locations
  export PATH="${HOME}/.opencode/bin:/usr/local/bin:${PATH}"
fi
if ! command -v opencode >/dev/null 2>&1; then
  echo "opencode not found on host PATH" >&2
  exit 127
fi

CFG="$ROOT/opencode-hub.host.jsonc"
"$ROOT/scripts/write-host-opencode-config.sh" "$CFG" >/dev/null

# Ensure hub is up and has spokes
if command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
  COMPOSE=(podman compose)
else
  COMPOSE=(docker compose)
fi

if ! "${COMPOSE[@]}" -f docker-compose.yml ps -q hub 2>/dev/null | grep -q .; then
  echo "starting lab…"
  ./scripts/up.sh
  sleep 5
  ./scripts/enroll.sh
fi

# If inventory empty, re-enroll + seed
SPOKES=$("${COMPOSE[@]}" -f docker-compose.yml exec -T hub \
  ansible-flow-mcp hub status 2>/dev/null | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("spokes") or []))' 2>/dev/null || echo 0)
if [ "${SPOKES:-0}" -lt 1 ]; then
  echo "no enrolled spokes — running enroll + seed…"
  ./scripts/enroll.sh
  ./scripts/seed_demo.sh
fi

export OPENCODE_CONFIG="$CFG"
echo "OpenCode → lab hub MCP via $CFG"
echo "Ask: list_nodes / hub_status to see spoke-01..03"
exec opencode "$@"
