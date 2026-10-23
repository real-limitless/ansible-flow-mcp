#!/bin/sh
# Start as root only long enough to hand the hub volume to ansible-flow.
set -eu
HUB="${ANSIBLE_FLOW_HUB_DIR:-/var/lib/ansible-flow/hub}"
mkdir -p "$HUB" /tmp/ansible-flow
if [ "$(id -u)" = "0" ]; then
  chown -R ansible-flow:ansible-flow "$HUB" /tmp/ansible-flow
  exec runuser --preserve-environment -u ansible-flow -- "$0"
fi
if [ ! -f "$HUB/inventory.yml" ]; then
  ansible-flow-mcp hub init --name "${ANSIBLE_FLOW_HUB_NAME:-hub-01}"
fi
exec ansible-flow-mcp serve \
  --host "${ANSIBLE_FLOW_HTTP_HOST:-0.0.0.0}" \
  --port "${ANSIBLE_FLOW_HTTP_PORT:-8789}"
