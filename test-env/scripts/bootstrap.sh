#!/usr/bin/env bash
# Start the always-on lab, wait until every flavor has enrolled, then smoke.
# Leaves the stack running.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib.sh
source "$ROOT/scripts/lib.sh"
"$ROOT/scripts/up.sh"

deadline=$((SECONDS + ${AFM_TEST_ENROLL_TIMEOUT:-240}))
echo "waiting for spoke enrollment"
until compose exec -T hub python3 -c 'import os,sys; from ansible_flow_mcp.hub.enroll import hub_status; w=set(os.environ.get("ANSIBLE_FLOW_TEST_SPOKES","").split()); h=set(hub_status().get("spokes") or []); sys.exit(0 if w and w<=h else 1)'
do
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "enrollment timed out; running smoke for the per-flavor reason" >&2
    break
  fi
  sleep 5
done

"$ROOT/scripts/smoke.sh"
echo "smoke finished; stack left running. Tear down with test-env/scripts/down.sh"
