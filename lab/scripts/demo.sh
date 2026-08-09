#!/usr/bin/env bash
# Full lab happy path: up → enroll → seed → smoke → ready banner → hub shell.
#
#   ./scripts/demo.sh              # drop into hub shell when TTY
#   ./scripts/demo.sh --no-shell   # CI / non-interactive
#   DEMO_NO_SHELL=1 ./scripts/demo.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DROP_SHELL=1
for arg in "$@"; do
  case "$arg" in
    --no-shell|-n) DROP_SHELL=0 ;;
    --shell) DROP_SHELL=1 ;;
    -h|--help)
      cat <<'EOF'
Usage: ./scripts/demo.sh [--no-shell]

  up → enroll → seed → smoke → banner
  Then opens an interactive shell on the hub (default if TTY).

  --no-shell   skip hub shell (for CI)
  DEMO_NO_SHELL=1  same
EOF
      exit 0
      ;;
  esac
done
if [ "${DEMO_NO_SHELL:-0}" = "1" ]; then
  DROP_SHELL=0
fi
# no TTY → never block on shell
if [ ! -t 0 ] || [ ! -t 1 ]; then
  DROP_SHELL=0
fi

./scripts/up.sh
echo ""
echo "== waiting a few seconds for health =="
sleep 5
./scripts/enroll.sh
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
║  Hub shell:      ./scripts/shell.sh   (or this demo drops in)║
║  Operator TUI:   ./scripts/tui.sh     |  ansible-flow-mcp tui║
║  OpenCode+hub:   ./scripts/opencode.sh | lab-opencode        ║
║  Status:         ansible-flow-mcp hub status                 ║
╚══════════════════════════════════════════════════════════════╝
EOF

if [ "$DROP_SHELL" = "1" ]; then
  echo ""
  echo "== dropping into hub shell (Ctrl-D or exit to leave) =="
  exec ./scripts/shell.sh
fi
