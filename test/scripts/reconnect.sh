#!/usr/bin/env bash
# After hub rebuild: ensure spokes enrolled, demo groups seeded, configs fresh.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
  COMPOSE=(podman compose)
else
  COMPOSE=(docker compose)
fi

echo "== ensure stack up =="
./scripts/up.sh
sleep 4

echo "== re-enroll spokes + seed groups =="
./scripts/enroll.sh
./scripts/seed_demo.sh

echo "== refresh OpenCode configs =="
"${COMPOSE[@]}" -f docker-compose.yml exec -T hub \
  ansible-flow-mcp hub write-opencode-config || true
./scripts/write-host-opencode-config.sh "$ROOT/opencode-hub.host.jsonc"

echo "== status =="
"${COMPOSE[@]}" -f docker-compose.yml exec -T hub ansible-flow-mcp hub status \
  | python3 -c 'import json,sys; s=json.load(sys.stdin); print("spokes:", s.get("spokes")); print("groups:", [g["name"] for g in s.get("groups") or []])'

cat <<EOF

Ready. Pick one:

  # OpenCode ON HOST → lab hub inventory (recommended after rebuild)
  ./scripts/opencode-host.sh

  # OpenCode INSIDE hub container
  ./scripts/opencode.sh

  # Operator TUI inside hub
  ./scripts/tui.sh

  # Hub shell
  ./scripts/shell.sh

EOF
