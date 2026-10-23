#!/bin/bash
# Place one-time join tokens on per-spoke drop dirs. Never print token values.
set -u
umask 077

HUB_DIR="${ANSIBLE_FLOW_HUB_DIR:-/var/lib/ansible-flow/hub}"
DROP="${ANSIBLE_FLOW_JOIN_DROP:-/run/join-drop}"
KEY_EXPORT="${ANSIBLE_FLOW_JOIN_KEY_EXPORT:-/run/join-key}"
GROUP_NAME="${ANSIBLE_FLOW_TEST_GROUP:-flavors}"

log() {
  python3 -c 'import json,sys
from datetime import datetime, timezone
print(json.dumps({"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "service": "ansible-flow-mcp", "environment": "test", "action": sys.argv[1], "outcome": sys.argv[2], "actor": "hub", "source_ip": "-", "request_id": "-", "spoke": sys.argv[3]}))' "$1" "$2" "$3"
}

export_join_key() {
  mkdir -p "$KEY_EXPORT"
  if [ ! -f "$HUB_DIR/keys/join_client" ]; then
    return 1
  fi
  cp -f "$HUB_DIR/keys/join_client" "$KEY_EXPORT/join_client"
  chmod 400 "$KEY_EXPORT/join_client"
}

issue_one() {
  name="$1"
  dest="$DROP/$name"
  mkdir -p "$dest"
  if python3 - "$name" <<'PY'
import json, subprocess, sys
name = sys.argv[1]
raw = subprocess.check_output(
    ["ansible-flow-mcp", "hub", "status"],
    text=True,
)
spokes = set(json.loads(raw).get("spokes") or [])
sys.exit(0 if name in spokes else 1)
PY
  then
    rm -f "$dest/token" "$dest/token.tmp"
    return 0
  fi
  refresh=0
  if [ ! -s "$dest/token" ]; then
    refresh=1
  elif [ -n "$(find "$dest/token" -mmin +10 -print 2>/dev/null)" ]; then
    refresh=1
  fi
  if [ "$refresh" != 1 ]; then
    return 0
  fi
  if ! json="$(ansible-flow-mcp hub issue-token --name "$name" --ttl 15m --public-addr "$name" 2>>"$HUB_DIR/autojoin.err")"; then
    log issue_join_token error "$name"
    return 0
  fi
  printf '%s' "$json" | python3 -c 'import json,sys; sys.stdout.write(json.load(sys.stdin)["token"])' >"$dest/token.tmp"
  chmod 400 "$dest/token.tmp"
  mv -f "$dest/token.tmp" "$dest/token"
  unset json
  log issue_join_token ok "$name"
}

seed_group() {
  [ -n "$GROUP_NAME" ] || return 0
  ANSIBLE_FLOW_TEST_GROUP="$GROUP_NAME" python3 - <<'PY' || true
import os
from ansible_flow_mcp.hub.enroll import create_group_op, hub_status, set_group_members_op

want = [p for p in os.environ.get("ANSIBLE_FLOW_TEST_SPOKES", "").split() if p]
group = os.environ.get("ANSIBLE_FLOW_TEST_GROUP") or "flavors"
if not want or not group:
    raise SystemExit(0)
st = hub_status()
spokes = set(st.get("spokes") or [])
if not set(want) <= spokes:
    raise SystemExit(0)
groups = {g["name"]: set(g.get("hosts") or []) for g in (st.get("groups") or [])}
if group not in groups:
    create_group_op(group)
    groups[group] = set()
if groups.get(group) != set(want):
    set_group_members_op(group, want)
PY
}

mkdir -p "$HUB_DIR"
touch "$HUB_DIR/autojoin.err"
chmod 600 "$HUB_DIR/autojoin.err" || true

while true; do
  export_join_key || true
  for name in ${ANSIBLE_FLOW_TEST_SPOKES:-}; do
    case "$name" in
      ""|*[!a-z0-9-]*) continue ;;
    esac
    issue_one "$name" || true
  done
  seed_group
  sleep 5
done
