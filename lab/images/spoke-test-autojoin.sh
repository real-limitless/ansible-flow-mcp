#!/bin/sh
# Read this spoke's join token from its private drop dir and enroll. Do not print the token.
set -u
umask 077

SPOKE_DIR="${ANSIBLE_FLOW_SPOKE_DIR:-/var/lib/ansible-flow/spoke}"
NAME="${SPOKE_NAME:-}"
DROP="${ANSIBLE_FLOW_JOIN_DROP:-/run/join-drop}"
KEY="${ANSIBLE_FLOW_JOIN_KEY:-/run/join-key/join_client}"
HUB="${ANSIBLE_FLOW_JOIN_HUB:-mcp-join@hub:22}"
ADDR="${ANSIBLE_FLOW_PUBLIC_ADDR:-$NAME}"

if [ -z "$NAME" ]; then
  echo "SPOKE_NAME is required" >&2
  exit 1
fi

fix_keys() {
  if [ -f /home/mcp-spoke/.ssh/authorized_keys ]; then
    chown mcp-spoke:mcp-spoke /home/mcp-spoke/.ssh/authorized_keys 2>/dev/null || true
    chmod 600 /home/mcp-spoke/.ssh/authorized_keys 2>/dev/null || true
  fi
  if [ -f /home/mcp-ansible/.ssh/authorized_keys ]; then
    chown mcp-ansible:mcp-ansible /home/mcp-ansible/.ssh/authorized_keys 2>/dev/null || true
    chmod 600 /home/mcp-ansible/.ssh/authorized_keys 2>/dev/null || true
  fi
}

while true; do
  if [ -f "$SPOKE_DIR/node.yml" ]; then
    fix_keys
    exit 0
  fi
  if [ -s "$DROP/token" ] && [ -f "$KEY" ]; then
    if ansible-flow-mcp spoke join \
      --token-file "$DROP/token" \
      --hub "$HUB" \
      --public-addr "$ADDR" \
      --name "$NAME" \
      --ssh-port 22 \
      --identity "$KEY" \
      --authorized-keys /home/mcp-spoke/.ssh/authorized_keys \
      >/dev/null
    then
      fix_keys
      echo "enrolled $NAME"
      exit 0
    fi
  fi
  sleep 3
done
