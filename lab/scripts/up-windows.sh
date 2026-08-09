#!/usr/bin/env bash
# Start Linux hub fabric + opt-in Windows guests (dockur). Requires KVM.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck source=lib.sh
source "$ROOT/scripts/lib.sh"

lab_compose_cmd
lab_require_kvm
lab_load_windows_env
lab_compose_files_windows

mkdir -p keys windows/client windows/server
touch keys/.gitkeep

echo "Using: ${COMPOSE[*]}"
echo "Windows: client=${WIN_CLIENT_VERSION} server=${WIN_SERVER_VERSION} user=${WIN_USERNAME}"
echo "First boot downloads ISOs and can take a long time (tens of minutes)."
lab_compose up -d --build "$@"
echo ""
lab_compose ps
echo ""
echo "Next:"
echo "  ./scripts/wait-windows.sh     # poll WinRM"
echo "  ./scripts/enroll-windows.sh   # register_target on hub"
echo "  ./scripts/smoke-windows.sh"
echo "Web UI (after install): http://127.0.0.1:8006 (client)  http://127.0.0.1:8007 (server)"
