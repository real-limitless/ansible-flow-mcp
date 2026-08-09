#!/usr/bin/env bash
# Poll WinRM on win-client / win-server from the hub until ready.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck source=lib.sh
source "$ROOT/scripts/lib.sh"

lab_compose_cmd
lab_load_windows_env
lab_compose_files_windows

TIMEOUT_SEC="${WIN_WAIT_TIMEOUT:-5400}"   # 90m first boot
INTERVAL_SEC="${WIN_WAIT_INTERVAL:-30}"
HOSTS=(win-client win-server)

echo "== wait for Windows containers =="
for h in "${HOSTS[@]}"; do
  if ! lab_compose ps --status running -q "$h" >/dev/null 2>&1; then
    if ! lab_compose ps -q "$h" 2>/dev/null | grep -q .; then
      echo "ERROR: service $h is not running — ./scripts/up-windows.sh first" >&2
      exit 1
    fi
  fi
done

echo "== poll WinRM from hub (timeout ${TIMEOUT_SEC}s, every ${INTERVAL_SEC}s) =="
echo "    user=${WIN_USERNAME}  (password from WIN_PASSWORD / windows/.env)"

START=$(date +%s)
while true; do
  NOW=$(date +%s)
  ELAPSED=$((NOW - START))
  if [ "$ELAPSED" -ge "$TIMEOUT_SEC" ]; then
    echo "ERROR: timed out after ${TIMEOUT_SEC}s waiting for WinRM" >&2
    echo "Check web UI :8006/:8007, OEM logs on Shared drive, container logs." >&2
    exit 1
  fi

  ALL_OK=1
  for h in "${HOSTS[@]}"; do
    # TCP 5985 open?
    if ! lab_run_hub bash -lc "timeout 3 bash -c 'echo >/dev/tcp/$h/5985' 2>/dev/null"; then
      echo "  [$ELAPSED s] $h:5985 not open yet"
      ALL_OK=0
      continue
    fi
    # WinRM identify (curl works without pywinrm)
    CODE=$(lab_run_hub bash -lc \
      "curl -s -o /dev/null -w '%{http_code}' --connect-timeout 5 -u '${WIN_USERNAME}:${WIN_PASSWORD}' \
       -H 'Content-Type: application/soap+xml;charset=UTF-8' \
       http://$h:5985/wsman 2>/dev/null || echo 000" || echo 000)
    # WinRM often returns 405/401/200 on bare GET — any non-000 means listener up
    if [ "$CODE" = "000" ]; then
      echo "  [$ELAPSED s] $h: WinRM HTTP no response"
      ALL_OK=0
    else
      echo "  [$ELAPSED s] $h: WinRM HTTP code=$CODE (listener up)"
    fi
  done

  if [ "$ALL_OK" = "1" ]; then
    echo "WinRM listeners reachable on ${HOSTS[*]}"
    exit 0
  fi
  sleep "$INTERVAL_SEC"
done
