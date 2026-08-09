#!/usr/bin/env bash
# Full lab happy path: up → enroll → seed → smoke → ready banner.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

./scripts/up.sh
echo ""
echo "== waiting a few seconds for health =="
sleep 5
./scripts/enroll.sh
# enroll calls seed; run again idempotently
./scripts/seed_demo.sh
./scripts/smoke.sh
./scripts/smoke_tui_opencode.sh

cat <<'EOF'

╔══════════════════════════════════════════════════════════════╗
║  ansible-flow hub lab READY                                  ║
╠══════════════════════════════════════════════════════════════╣
║  spokes:                                                     ║
║    spoke-01  web/edge     groups: web, edge, prod            ║
║    spoke-02  app/canary   groups: app, canary, prod          ║
║    spoke-03  data/batch   groups: data, batch, prod          ║
║  groups: prod web app data edge batch canary                 ║
║                                                              ║
║  Operator TUI:   ./scripts/tui.sh                            ║
║  OpenCode+hub:   ./scripts/opencode.sh                       ║
║  Status:         docker compose exec hub ansible-flow-mcp \  ║
║                    hub status                                ║
╚══════════════════════════════════════════════════════════════╝
EOF
