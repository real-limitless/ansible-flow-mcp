#!/usr/bin/env bash
# Verify Windows targets: kind=target, win_ping, spoke_call rejected.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck source=lib.sh
source "$ROOT/scripts/lib.sh"

lab_compose_cmd
lab_load_windows_env
lab_compose_files_windows

HOSTS=(win-client win-server)

echo "== hub status (expect targets) =="
lab_run_hub ansible-flow-mcp hub status

echo "== kind=target for Windows hosts =="
lab_run_hub python3 - <<'PY'
import json, subprocess
st = json.loads(subprocess.check_output(["ansible-flow-mcp", "hub", "status"]))
targets = set(st.get("targets") or [])
need = {"win-client", "win-server"}
missing = need - targets
if missing:
    raise SystemExit(f"missing targets {sorted(missing)} — run enroll-windows.sh")
by_name = {n["name"]: n for n in (st.get("nodes") or [])}
for h in need:
    k = (by_name.get(h) or {}).get("kind")
    if k != "target":
        raise SystemExit(f"{h} kind={k!r} want target")
    if "password" in json.dumps(by_name[h]).lower():
        raise SystemExit(f"password leaked in hub status for {h}")
print("ok kinds + no password in status")
PY

echo "== spoke_call must fail on targets =="
for h in "${HOSTS[@]}"; do
  set +e
  OUT=$(lab_run_hub ansible-flow-mcp hub spoke-call --node "$h" --tool list_collections --timeout 10 2>&1)
  RC=$?
  set -e
  if [ "$RC" -eq 0 ]; then
    echo "FAIL: spoke_call succeeded on target $h" >&2
    echo "$OUT" >&2
    exit 1
  fi
  if ! echo "$OUT" | grep -qiE 'target|not a mesh|not enrolled'; then
    echo "FAIL: unexpected spoke_call error for $h:" >&2
    echo "$OUT" >&2
    exit 1
  fi
  echo "ok: spoke_call rejected $h"
done

echo "== ansible win_ping via hub inventory =="
lab_run_hub bash -lc '
  set -e
  export ANSIBLE_FLOW_ROLE=hub ANSIBLE_FLOW_HUB_DIR=/var/lib/ansible-flow/hub
  export ANSIBLE_HOST_KEY_CHECKING=False
  for h in win-client win-server; do
    echo "-- win_ping $h --"
    timeout 90 ansible "$h" -m ansible.windows.win_ping \
      -i /var/lib/ansible-flow/hub/inventory.yml
  done
'

echo "== run_module policy allows targets =="
lab_run_hub python3 - <<'PY'
from ansible_flow_mcp.policy import Role, assert_hosts_allowed, load_enrolled_hosts, load_inventory_groups
from ansible_flow_mcp.paths import hub_dir
inv = hub_dir() / "inventory.yml"
enrolled = load_enrolled_hosts(inv)
groups = load_inventory_groups(inv)
assert assert_hosts_allowed("win-client", enrolled=enrolled, role=Role.HUB, groups=groups) == "win-client"
assert assert_hosts_allowed("windows", enrolled=enrolled, role=Role.HUB, groups=groups) == "windows"
print("ok policy")
PY

echo "SMOKE WINDOWS OK"
