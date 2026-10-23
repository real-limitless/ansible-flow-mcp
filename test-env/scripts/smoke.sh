#!/usr/bin/env bash
# Connectivity smoke only: enrollment, TCP/22, hub status, spoke-call list_collections.
# Does not run playbooks or ad-hoc modules.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib.sh
source "$ROOT/scripts/lib.sh"
cd "$ROOT"

compose exec -T hub python3 - <<'PY'
import os
import socket
import sys

from ansible_flow_mcp.hub.enroll import hub_status
from ansible_flow_mcp.ssh import spoke_call

want = [p for p in os.environ.get("ANSIBLE_FLOW_TEST_SPOKES", "").split() if p]
if not want:
    print("FAIL hub: ANSIBLE_FLOW_TEST_SPOKES is empty")
    raise SystemExit(1)

status = hub_status()
enrolled = list(status.get("spokes") or [])
print(f"hub name={status.get('name')} spokes={','.join(enrolled) or '-'}")
failed = 0
print(f"{'flavor':<12} {'enrolled':<10} {'ssh':<6} {'spoke_call':<12} result")
for name in want:
    is_in = name in enrolled
    ssh_ok = False
    call_ok = False
    detail = ""
    if is_in:
        try:
            sock = socket.create_connection((name, 22), 8)
            sock.close()
            ssh_ok = True
        except OSError as exc:
            detail = f"ssh:{exc.__class__.__name__}"
        try:
            result = spoke_call(name, tool="list_collections", timeout=90)
            call_ok = bool(result.ok)
            if not call_ok:
                err = (result.stderr or result.stdout or "spoke_call failed")[:180]
                detail = err.replace("\n", " ")
        except Exception as exc:  # noqa: BLE001
            detail = exc.__class__.__name__
    else:
        detail = "not enrolled"
    ok = is_in and ssh_ok and call_ok
    if not ok:
        failed += 1
    print(
        f"{name:<12} {'yes' if is_in else 'no':<10} "
        f"{'yes' if ssh_ok else 'no':<6} {'yes' if call_ok else 'no':<12} "
        f"{'PASS' if ok else 'FAIL'} {detail}".rstrip()
    )

missing = [n for n in want if n not in enrolled]
extra = [n for n in enrolled if n not in want]
if missing or extra:
    print(f"list mismatch missing={missing or '-'} extra={extra or '-'}")
print(f"summary failed={failed} expected={len(want)} enrolled={len(enrolled)}")
raise SystemExit(1 if failed or missing else 0)
PY
