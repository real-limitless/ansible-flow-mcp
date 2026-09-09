#!/bin/sh
set -eu
HUB="${ANSIBLE_FLOW_HUB_DIR:-/var/lib/ansible-flow/hub}"
mkdir -p "$HUB"
if [ ! -f "$HUB/inventory.yml" ]; then
  ansible-flow-mcp hub init --name "${ANSIBLE_FLOW_HUB_NAME:-hub-01}"
fi
exec ansible-flow-mcp serve --host 0.0.0.0 --port "${ANSIBLE_FLOW_HTTP_PORT:-8789}"
