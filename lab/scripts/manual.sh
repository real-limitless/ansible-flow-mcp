#!/usr/bin/env bash
# Bring lab containers up without auto enroll / seed / smoke.
# You initialize mesh spokes (and optional WinRM targets) by hand.
#
#   ./scripts/manual.sh                 # hub init done; no spokes enrolled
#   ./scripts/manual.sh --blank          # skip hub init too
#   ./scripts/manual.sh --fresh          # wipe hub-data volume first
#   ./scripts/manual.sh --windows        # also start dockur Windows guests (no register)
#   ./scripts/manual.sh --no-shell
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck source=lib.sh
source "$ROOT/scripts/lib.sh"

FRESH=0
BLANK=0
WINDOWS=0
DROP_SHELL=1

for arg in "$@"; do
  case "$arg" in
    --fresh) FRESH=1 ;;
    --blank) BLANK=1 ;;
    --windows) WINDOWS=1 ;;
    --no-shell|-n) DROP_SHELL=0 ;;
    --shell) DROP_SHELL=1 ;;
    -h|--help)
      cat <<'EOF'
Usage: ./scripts/manual.sh [options]

  Start hub + Linux spokes (compose) without enroll/seed/smoke.
  Practice hub init / invite / spoke join / register-target yourself.

Options:
  --fresh      compose down -v (wipe hub-data) then up
  --blank      skip hub init (ANSIBLE_FLOW_SKIP_HUB_INIT=1)
  --windows    also up-windows.sh (dockur guests; no enroll-windows)
  --no-shell   do not drop into hub shell
  --shell      force hub shell when TTY

After blank hub init inside the hub:
  ansible-flow-mcp hub init --name hub-01
  ansible-flow-mcp hub write-opencode-config   # optional

Full auto anytime:
  ./scripts/enroll.sh
  ./scripts/demo.sh
  ./scripts/enroll-windows.sh   # if Windows overlay is up
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $arg (try --help)" >&2
      exit 1
      ;;
  esac
done

if [ "${DEMO_NO_SHELL:-0}" = "1" ]; then
  DROP_SHELL=0
fi
if [ ! -t 0 ] || [ ! -t 1 ]; then
  DROP_SHELL=0
fi

lab_compose_cmd
lab_compose_files_base

if [ "$FRESH" = "1" ]; then
  echo "== fresh: compose down -v =="
  # tear down base (+ windows overlay if present) and volumes
  lab_compose_files_windows
  lab_compose down -v 2>/dev/null || true
  lab_compose_files_base
  lab_compose down -v 2>/dev/null || true
fi

if [ "$BLANK" = "1" ]; then
  export ANSIBLE_FLOW_SKIP_HUB_INIT=1
  echo "== blank hub: ANSIBLE_FLOW_SKIP_HUB_INIT=1 =="
else
  export ANSIBLE_FLOW_SKIP_HUB_INIT=0
fi

echo "== up (no enroll) =="
./scripts/up.sh

echo ""
echo "== waiting for sshd =="
sleep 4
# hub healthy = port 22 (hub_id optional when --blank)
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if lab_compose exec -T hub bash -lc "ss -lnt | grep -q ':22'" 2>/dev/null; then
    break
  fi
  sleep 2
done

if [ "$WINDOWS" = "1" ]; then
  echo ""
  echo "== windows overlay (containers only; no register-target) =="
  ./scripts/up-windows.sh
fi

HUB_STATE="unknown"
if lab_compose exec -T hub test -f /var/lib/ansible-flow/hub/hub_id 2>/dev/null; then
  HUB_STATE="initialized (hub_id present)"
else
  HUB_STATE="NOT initialized — run hub init inside hub"
fi

cat <<EOF

╔══════════════════════════════════════════════════════════════╗
║  ansible-flow lab MANUAL mode                                ║
╠══════════════════════════════════════════════════════════════╣
║  Containers are up. No auto enroll / seed / smoke.           ║
║  Hub state: ${HUB_STATE}
║                                                              ║
║  Hub shell:   ./scripts/shell.sh                             ║
║  Operator TUI: ./scripts/tui.sh   (i = invite + join cmd)    ║
║                                                              ║
║  Mesh spokes (SSH join):                                     ║
║    # on hub                                                  ║
║    ansible-flow-mcp hub init --name hub-01   # if --blank    ║
║    ansible-flow-mcp hub issue-token --name spoke-01 --ttl 15m\\
║      --hub mcp-join@hub:22 --public-addr spoke-01            ║
║    # on spoke-01 container                                   ║
║    ansible-flow-mcp spoke join --token '…' \\                 ║
║      --hub mcp-join@hub:22 --public-addr spoke-01            ║
║                                                              ║
║  Ansible targets (WinRM, no agent) — if --windows:           ║
║    ./scripts/wait-windows.sh                                 ║
║    # then register by hand, or: ./scripts/enroll-windows.sh  ║
║    # never spoke_call on targets                             ║
║                                                              ║
║  Later full auto:  ./scripts/enroll.sh | ./scripts/demo.sh   ║
╚══════════════════════════════════════════════════════════════╝
EOF

if [ "$BLANK" = "1" ]; then
  cat <<'EOF'

Note (--blank): after hub init, write OpenCode config (optional):
  ansible-flow-mcp hub write-opencode-config

Join channel (mcp-join keys) is already prepared by the hub entrypoint.

EOF
fi

if [ "$DROP_SHELL" = "1" ]; then
  echo ""
  echo "== dropping into hub shell (Ctrl-D or exit to leave) =="
  exec ./scripts/shell.sh
fi
