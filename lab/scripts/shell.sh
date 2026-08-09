#!/usr/bin/env bash
# Interactive shell on the lab hub (inventory already enrolled/seeded).
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

if [ ! -t 0 ] || [ ! -t 1 ]; then
  echo "shell.sh needs an interactive TTY (run from a real terminal)." >&2
  exit 1
fi

# Ensure hub is up
if ! "${COMPOSE[@]}" -f docker-compose.yml ps --status running -q hub 2>/dev/null | grep -q .; then
  if ! "${COMPOSE[@]}" -f docker-compose.yml ps -q hub 2>/dev/null | grep -q .; then
    echo "hub not running — try: ./scripts/up.sh && ./scripts/enroll.sh" >&2
    exit 1
  fi
fi

exec "${COMPOSE[@]}" -f docker-compose.yml exec -it \
  -e ANSIBLE_FLOW_HUB_DIR=/var/lib/ansible-flow/hub \
  -e ANSIBLE_FLOW_ROLE=hub \
  -e PATH="/root/.opencode/bin:/usr/local/bin:/usr/bin:/bin" \
  hub bash -lc '
set -e
export ANSIBLE_FLOW_HUB_DIR=/var/lib/ansible-flow/hub
export ANSIBLE_FLOW_ROLE=hub
export PATH="/root/.opencode/bin:/usr/local/bin:${PATH}"
cd /var/lib/ansible-flow/hub
cat <<EOF

── hub lab shell ─────────────────────────────────────────
  hub dir:  $ANSIBLE_FLOW_HUB_DIR
  status:   ansible-flow-mcp hub status
  tui:      ansible-flow-mcp tui
  ai:       lab-opencode
  call:     ansible-flow-mcp hub spoke-call --node spoke-01 --tool list_collections
──────────────────────────────────────────────────────────

EOF
exec bash -i
'
