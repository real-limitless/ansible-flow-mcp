#!/usr/bin/env bash
# Write OpenCode config on the HOST that bridges MCP into the lab hub container.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

HUB_MCP="$ROOT/scripts/hub-mcp.sh"
chmod +x "$HUB_MCP"

OUT="${1:-$ROOT/opencode-hub.host.jsonc}"
cat >"$OUT" <<EOF
{
  "\$schema": "https://opencode.ai/config.json",
  "mcp": {
    "ansible-flow-hub": {
      "type": "local",
      "command": ["$HUB_MCP"],
      "enabled": true,
      "timeout": 120000
    }
  }
}
EOF

echo "Wrote $OUT"
echo ""
echo "Start OpenCode with lab hub inventory:"
echo "  OPENCODE_CONFIG=$OUT opencode"
echo "  # or: cd test && OPENCODE_CONFIG=./opencode-hub.host.jsonc ./scripts/opencode-host.sh"
