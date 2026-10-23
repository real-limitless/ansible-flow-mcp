#!/bin/bash
# Place one-time join tokens on per-spoke drop dirs. Never print token values.
# Exit once every spoke is enrolled and the lab group matches, so an idle hub
# does not keep starting interpreters.
set -u
umask 077

HUB_DIR="${ANSIBLE_FLOW_HUB_DIR:-/var/lib/ansible-flow/hub}"
DROP="${ANSIBLE_FLOW_JOIN_DROP:-/run/join-drop}"
KEY_EXPORT="${ANSIBLE_FLOW_JOIN_KEY_EXPORT:-/run/join-key}"

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

mkdir -p "$HUB_DIR"
touch "$HUB_DIR/autojoin.err"
chmod 600 "$HUB_DIR/autojoin.err" || true

attempt=0
while true; do
  export_join_key || true
  names="$(python3 /usr/local/bin/hub_autojoin.py)" && {
    for name in ${ANSIBLE_FLOW_TEST_SPOKES:-}; do
      rm -f "$DROP/$name/token" "$DROP/$name/token.tmp"
    done
    exit 0
  }
  for name in $names; do
    case "$name" in
      ""|*[!a-z0-9-]*) continue ;;
    esac
    issue_one "$name" || true
  done
  # A missing hub or a spoke that has not joined yet must not spin.
  if [ "$attempt" -gt 12 ]; then
    sleep 30
  else
    sleep 5
  fi
  attempt=$((attempt + 1))
done
