#!/usr/bin/env bash
# Bring lab containers up without auto enroll / seed / smoke.
# You initialize mesh spokes (and optional WinRM targets) by hand.
#
#   ./scripts/manual.sh                 # hub init done; no spokes enrolled
#   ./scripts/manual.sh --blank          # wipe hub-data + skip hub init (true blank)
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
KEEP_VOLUME=0

for arg in "$@"; do
  case "$arg" in
    --fresh) FRESH=1 ;;
    --blank) BLANK=1 ;;
    --keep-volume) KEEP_VOLUME=1 ;;
    --windows) WINDOWS=1 ;;
    --no-shell|-n) DROP_SHELL=0 ;;
    --shell) DROP_SHELL=1 ;;
    -h|--help)
      cat <<'EOF'
Usage: ./scripts/manual.sh [options]

  Start hub + Linux spokes (compose) without enroll/seed/smoke.
  Practice hub init / invite / spoke join / register-target yourself.

Options:
  --blank         True empty hub: wipe hub-data, skip hub init/join/opencode
  --fresh         Wipe hub-data (and stop stack) then up
  --keep-volume   With --blank: do not wipe (only works if volume has no hub_id)
  --windows       also up-windows.sh (dockur guests; no enroll-windows)
  --no-shell      do not drop into hub shell
  --shell         force hub shell when TTY

Blank workflow:
  ./scripts/manual.sh --blank --no-shell
  ./scripts/shell.sh
  # inside hub:
  ansible-flow-mcp hub init --name hub-01
  exit
  # reinstall join keys + opencode (SKIP cleared, hub_id present):
  ANSIBLE_FLOW_SKIP_HUB_INIT=0 ./scripts/up.sh
  # or: compose up -d --force-recreate hub

Full auto anytime:
  ./scripts/enroll.sh
  ./scripts/demo.sh
  ./scripts/enroll-windows.sh
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

# --blank implies wipe unless --keep-volume
if [ "$BLANK" = "1" ] && [ "$KEEP_VOLUME" = "0" ]; then
  FRESH=1
fi

wipe_stack() {
  echo "== fresh: compose down -v (wipe hub-data) =="
  lab_compose_files_windows
  lab_compose down -v 2>/dev/null || true
  lab_compose_files_base
  lab_compose down -v 2>/dev/null || true
  # host-side join key copies from prior runs
  rm -f "$ROOT/keys/join_client" "$ROOT/keys/join_client.pub" \
    "$ROOT/keys/hub_client.pub" 2>/dev/null || true
}

if [ "$FRESH" = "1" ]; then
  wipe_stack
fi

if [ "$BLANK" = "1" ]; then
  export ANSIBLE_FLOW_SKIP_HUB_INIT=1
  echo "== blank hub: ANSIBLE_FLOW_SKIP_HUB_INIT=1 =="
else
  export ANSIBLE_FLOW_SKIP_HUB_INIT=0
fi

echo "== up (no enroll; force-recreate so env applies) =="
mkdir -p keys
touch keys/.gitkeep
lab_compose_files_base
echo "Using: ${COMPOSE[*]}  SKIP_HUB_INIT=${ANSIBLE_FLOW_SKIP_HUB_INIT}"
# force-recreate so ANSIBLE_FLOW_SKIP_HUB_INIT is not stuck on an old container
lab_compose up -d --build --force-recreate
echo "Waiting for health..."
sleep 3
lab_compose ps

echo ""
echo "== waiting for sshd =="
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
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

# --- verify blank really blank ---
if [ "$BLANK" = "1" ]; then
  if lab_compose exec -T hub test -f /var/lib/ansible-flow/hub/hub_id 2>/dev/null; then
    cat >&2 <<'EOF'
ERROR: --blank but hub_id still present on the hub volume.

  Stale hub-data was not wiped, or the hub container was not recreated.
  Fix:
    ./scripts/manual.sh --fresh --blank --no-shell

EOF
    exit 1
  fi
  # join channel should not exist yet
  if lab_compose exec -T hub test -f /var/lib/ansible-flow/hub/keys/hub_client 2>/dev/null; then
    echo "WARNING: hub_client key present in blank mode (unexpected)" >&2
  fi
  HUB_STATE="BLANK — no hub_id (run hub init yourself)"
else
  if lab_compose exec -T hub test -f /var/lib/ansible-flow/hub/hub_id 2>/dev/null; then
    HUB_STATE="initialized (hub_id present); spokes not auto-enrolled"
  else
    HUB_STATE="NOT initialized — unexpected; check hub logs"
  fi
fi

# confirm env inside container
SKIP_INSIDE=$(lab_compose exec -T hub bash -lc 'echo "${ANSIBLE_FLOW_SKIP_HUB_INIT:-unset}"' 2>/dev/null | tr -d '\r' || echo unset)

cat <<EOF

╔══════════════════════════════════════════════════════════════╗
║  ansible-flow lab MANUAL mode                                ║
╠══════════════════════════════════════════════════════════════╣
║  Containers are up. No auto enroll / seed / smoke.           ║
║  Hub state: ${HUB_STATE}
║  SKIP_HUB_INIT in container: ${SKIP_INSIDE}
║                                                              ║
║  Hub shell:   ./scripts/shell.sh                             ║
║  Operator TUI: ./scripts/tui.sh   (i = invite + join cmd)    ║
║                                                              ║
║  Mesh spokes (SSH join):                                     ║
║    # on hub                                                  ║
║    ansible-flow-mcp hub init --name hub-01   # if blank      ║
║    # then recreate hub with SKIP=0 to install join keys:     ║
║    #   ANSIBLE_FLOW_SKIP_HUB_INIT=0 ./scripts/up.sh          ║
║    ansible-flow-mcp hub issue-token --name spoke-01 --ttl 15m\\
║      --hub mcp-join@hub:22 --public-addr spoke-01            ║
║    # on spoke-01 container                                   ║
║    ansible-flow-mcp spoke join --token '…' \\                 ║
║      --hub mcp-join@hub:22 --public-addr spoke-01            ║
║                                                              ║
║  Ansible targets (WinRM) — if --windows:                     ║
║    ./scripts/wait-windows.sh                                 ║
║    # then register by hand, or: ./scripts/enroll-windows.sh  ║
║                                                              ║
║  Later full auto:  ./scripts/enroll.sh | ./scripts/demo.sh   ║
╚══════════════════════════════════════════════════════════════╝
EOF

if [ "$BLANK" = "1" ]; then
  cat <<'EOF'

Blank checklist (inside hub after shell):
  1. ls /var/lib/ansible-flow/hub     # should be empty / no hub_id
  2. ansible-flow-mcp hub init --name hub-01
  3. exit; ANSIBLE_FLOW_SKIP_HUB_INIT=0 ./scripts/up.sh
     # restarts hub → join keys + mcp-join authorized_keys + opencode
  4. invite / spoke join by hand

EOF
fi

if [ "$DROP_SHELL" = "1" ]; then
  echo ""
  echo "== dropping into hub shell (Ctrl-D or exit to leave) =="
  exec ./scripts/shell.sh
fi
