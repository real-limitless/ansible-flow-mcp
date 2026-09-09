#!/usr/bin/env bash
# Register this plane as an mcp-flow stdio backend.
set -euo pipefail

MCP_FLOW_URL="${MCP_FLOW_URL:-http://127.0.0.1:8787}"
MCP_FLOW_URL="${MCP_FLOW_URL%/}"
TOKEN="${MCP_FLOW_ADMIN_TOKEN:-}"
if [[ -z "$TOKEN" ]]; then
  echo "Set MCP_FLOW_ADMIN_TOKEN (mcp-flow admin bearer)." >&2
  exit 1
fi

SLUG="${1:-ansible-flow}"
CMD_JSON='["ansible-flow-mcp"]'

curl -fsS -X POST "$MCP_FLOW_URL/v1/backends" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d "{\"slug\":\"$SLUG\",\"title\":\"ansible-flow-mcp\",\"transport\":\"stdio\",\"command\":$CMD_JSON,\"enabled\":true,\"placement\":{\"mode\":\"central-sandbox\"}}"
echo
