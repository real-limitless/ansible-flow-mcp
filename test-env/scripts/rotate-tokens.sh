#!/usr/bin/env bash
# Replace the test MCP bearer and the admin token. Prints paths only, never values.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib.sh
source "$ROOT/scripts/lib.sh"
cd "$ROOT"
compose exec -T hub sh -c '
  set -eu
  hub="${ANSIBLE_FLOW_HUB_DIR:-/var/lib/ansible-flow/hub}"
  rm -f "$hub/mcp.http.token" "$hub/admin.token"
  for name in mcp-http admin; do
    pidfile="/var/run/ansible-flow-${name}.pid"
    if [ -f "$pidfile" ]; then
      kill "$(cat "$pidfile")" 2>/dev/null || true
    fi
  done
'
ok=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if compose exec -T hub sh -c '
    hub="${ANSIBLE_FLOW_HUB_DIR:-/var/lib/ansible-flow/hub}"
    test -s "$hub/mcp.http.token" && test -s "$hub/admin.token"
  '; then
    ok=1
    break
  fi
  sleep 1
done
if [ "$ok" != 1 ]; then
  echo "token files were not recreated; restart the hub service" >&2
  exit 1
fi
echo "rotated. Read these on the hub only; do not paste them into tickets or logs:"
echo "  /var/lib/ansible-flow/hub/mcp.http.token"
echo "  /var/lib/ansible-flow/hub/admin.token"
compose exec -T hub sh -c '
  hub="${ANSIBLE_FLOW_HUB_DIR:-/var/lib/ansible-flow/hub}"
  wc -c "$hub/mcp.http.token" "$hub/admin.token"
'
