#!/bin/bash
set -euo pipefail

HUB_DIR="${ANSIBLE_FLOW_HUB_DIR:-/var/lib/ansible-flow/hub}"
export ANSIBLE_FLOW_ROLE=hub
export ANSIBLE_FLOW_HUB_DIR="$HUB_DIR"

mkdir -p "$HUB_DIR" /var/run/sshd /home/mcp-join/.ssh
chmod 700 /home/mcp-join/.ssh

# Shared group so mcp-join (accept-join ForceCommand) can update inventory
groupadd -f ansible-flow 2>/dev/null || true
usermod -aG ansible-flow mcp-hub 2>/dev/null || true
usermod -aG ansible-flow mcp-join 2>/dev/null || true
usermod -s /bin/bash mcp-join 2>/dev/null || true
passwd -u mcp-join 2>/dev/null || usermod -p '*' mcp-join 2>/dev/null || true

# Host keys
if [ ! -f /etc/ssh/ssh_host_ed25519_key ]; then
  ssh-keygen -A
fi

# Initialize hub once
if [ ! -f "$HUB_DIR/hub_id" ]; then
  ansible-flow-mcp hub init --name hub-01
fi
chown -R mcp-hub:ansible-flow "$HUB_DIR" || chown -R mcp-hub:mcp-hub "$HUB_DIR" || true
chmod -R g+rwX "$HUB_DIR" || true
find "$HUB_DIR/keys" -type f ! -name '*.pub' -exec chmod 640 {} \; 2>/dev/null || true
find "$HUB_DIR/ca" -type f -exec chmod 640 {} \; 2>/dev/null || true
chmod 660 "$HUB_DIR/known_hosts" 2>/dev/null || true
chmod 660 "$HUB_DIR/inventory.yml" 2>/dev/null || true
chmod 660 "$HUB_DIR/tokens/replay.db" 2>/dev/null || true
chmod 660 "$HUB_DIR/audit.jsonl" 2>/dev/null || true

# Lab join identity
JOIN_KEY="$HUB_DIR/keys/join_client"
if [ ! -f "$JOIN_KEY" ]; then
  ssh-keygen -t ed25519 -N "" -C "lab-join" -f "$JOIN_KEY" -q
fi
JOIN_PUB=$(cat "${JOIN_KEY}.pub")
AUTH=/home/mcp-join/.ssh/authorized_keys
echo "$JOIN_PUB" >"$AUTH"
chmod 600 "$AUTH"
chown mcp-join:mcp-join "$AUTH" /home/mcp-join/.ssh

if [ -d /lab/keys ] && [ -w /lab/keys ]; then
  cp -f "$JOIN_KEY" /lab/keys/join_client
  cp -f "${JOIN_KEY}.pub" /lab/keys/join_client.pub
  cp -f "$HUB_DIR/keys/hub_client.pub" /lab/keys/hub_client.pub 2>/dev/null || true
  chmod 644 /lab/keys/*.pub 2>/dev/null || true
fi

# OpenCode hub MCP config (for TUI key A + lab-opencode)
export PATH="/root/.opencode/bin:/usr/local/bin:${PATH}"
if ! ansible-flow-mcp --hub-dir "$HUB_DIR" hub write-opencode-config; then
  python3 - <<'PY'
import json, shutil
from pathlib import Path
import os
hub = Path(os.environ.get("ANSIBLE_FLOW_HUB_DIR", "/var/lib/ansible-flow/hub"))
bin_path = shutil.which("ansible-flow-mcp") or "/usr/local/bin/ansible-flow-mcp"
cfg = {
    "$schema": "https://opencode.ai/config.json",
    "mcp": {
        "ansible-flow-hub": {
            "type": "local",
            "command": [bin_path, "hub", "session"],
            "enabled": True,
            "environment": {
                "ANSIBLE_FLOW_HUB_DIR": str(hub),
                "ANSIBLE_FLOW_ROLE": "hub",
            },
        }
    },
}
path = hub / "opencode-hub.jsonc"
path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
print("wrote", path)
PY
fi
# ensure group can read config
chmod 664 "$HUB_DIR/opencode-hub.jsonc" 2>/dev/null || true

echo "[hub] starting sshd; hub_id=$(cat "$HUB_DIR/hub_id"); opencode=$(command -v opencode || echo missing); cfg=$HUB_DIR/opencode-hub.jsonc"
exec /usr/sbin/sshd -D -e
