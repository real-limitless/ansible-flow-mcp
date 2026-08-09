#!/usr/bin/env bash
# After enroll.sh: verify hub→spoke ForceCommand MCP (no shell) + spoke_call.
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

run_hub() { "${COMPOSE[@]}" -f docker-compose.yml exec -T hub "$@"; }

echo "== hub status =="
run_hub ansible-flow-mcp hub status

SPOKES=$(run_hub python3 -c 'import json,sys,subprocess; print(" ".join(json.loads(subprocess.check_output(["ansible-flow-mcp","hub","status"])).get("spokes") or []))')
if [ -z "${SPOKES// }" ]; then
  echo "No enrolled spokes — run ./scripts/enroll.sh first" >&2
  exit 1
fi

for s in $SPOKES; do
  echo "== spoke_call $s list_collections =="
  run_hub ansible-flow-mcp hub spoke-call --node "$s" --tool list_collections --timeout 45

  echo "== ForceCommand must not yield shell on $s =="
  # If ForceCommand works, requesting a shell still runs MCP / non-shell
  set +e
  OUT=$(run_hub bash -lc "ssh -i /var/lib/ansible-flow/hub/keys/hub_client -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/var/lib/ansible-flow/hub/known_hosts mcp-spoke@$s 'echo SHELL_LEAK'" 2>&1)
  RC=$?
  set -e
  if echo "$OUT" | grep -q 'SHELL_LEAK'; then
    echo "FAIL: shell leak on $s" >&2
    echo "$OUT" >&2
    exit 1
  fi
  echo "ok: no shell leak (ssh rc=$RC)"
done

echo "== reject non-enrolled host =="
set +e
REJ=$(run_hub bash -lc 'ANSIBLE_FLOW_ROLE=hub ansible-flow-mcp hub session' 2>&1 | head -1)
# use python policy check inside hub
run_hub python3 - <<'PY'
from ansible_flow_mcp.policy import Role, assert_hosts_allowed
from ansible_flow_mcp.hub.inventory import load_inventory, enrolled_host_names
from ansible_flow_mcp.paths import hub_dir
inv = load_inventory(hub_dir() / "inventory.yml")
enrolled = enrolled_host_names(inv)
try:
    assert_hosts_allowed("not-enrolled-host", enrolled=enrolled, role=Role.HUB)
    raise SystemExit("should have rejected")
except ValueError as e:
    print("ok rejected:", e)
PY

echo "SMOKE OK"
