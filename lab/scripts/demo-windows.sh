#!/usr/bin/env bash
# Opt-in: Linux fabric (if needed) + Windows guests → WinRM targets → smoke.
#
#   ./scripts/demo-windows.sh
#   ./scripts/demo-windows.sh --skip-linux   # Windows overlay only (hub already up)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SKIP_LINUX=0
for arg in "$@"; do
  case "$arg" in
    --skip-linux) SKIP_LINUX=1 ;;
    -h|--help)
      cat <<'EOF'
Usage: ./scripts/demo-windows.sh [--skip-linux]

  Requires KVM, large disk, and a long first boot (ISO download + install).
  Attaches win-client (Win11) and win-server (2022) as hub Ansible targets.

  --skip-linux   do not run Linux enroll/smoke (hub must already be up)
EOF
      exit 0
      ;;
  esac
done

if [ "$SKIP_LINUX" = "0" ]; then
  # Ensure Linux spokes exist (demo --no-shell path without hub shell)
  if [ ! -x ./scripts/demo.sh ]; then
    echo "missing ./scripts/demo.sh" >&2
    exit 1
  fi
  # Only up+enroll if hub not healthy
  # shellcheck source=lib.sh
  source "$ROOT/scripts/lib.sh"
  lab_compose_cmd
  lab_compose_files_base
  if ! lab_compose exec -T hub ansible-flow-mcp hub status >/dev/null 2>&1; then
    echo "== Linux fabric first (demo.sh --no-shell) =="
    ./scripts/demo.sh --no-shell
  else
    echo "== hub already up — skip full Linux demo =="
    ./scripts/enroll.sh || true
    ./scripts/seed_demo.sh || true
  fi
fi

./scripts/up-windows.sh
echo ""
echo "== waiting for WinRM (first boot can take a long time) =="
./scripts/wait-windows.sh
./scripts/enroll-windows.sh
./scripts/smoke-windows.sh

cat <<'EOF'

╔══════════════════════════════════════════════════════════════╗
║  ansible-flow Windows lab READY (targets)                    ║
╠══════════════════════════════════════════════════════════════╣
║  win-client   Windows 11     WinRM target  groups: windows   ║
║  win-server   Server 2022    WinRM target  groups: windows   ║
║                                                              ║
║  Web UI:  http://127.0.0.1:8006  (client)                    ║
║           http://127.0.0.1:8007  (server)                    ║
║  Status:  ansible-flow-mcp hub status                        ║
║  Ping:    ansible win-client -m ansible.windows.win_ping \   ║
║             -i $ANSIBLE_FLOW_HUB_DIR/inventory.yml           ║
╚══════════════════════════════════════════════════════════════╝
EOF
