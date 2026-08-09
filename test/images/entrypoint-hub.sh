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
# nologin/locked accounts are rejected by sshd — unlock join user (ForceCommand is the jail)
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
# private keys stay group-readable for mcp-join accept-join path
find "$HUB_DIR/keys" -type f ! -name '*.pub' -exec chmod 640 {} \; 2>/dev/null || true
find "$HUB_DIR/ca" -type f -exec chmod 640 {} \; 2>/dev/null || true
chmod 660 "$HUB_DIR/known_hosts" 2>/dev/null || true
chmod 660 "$HUB_DIR/inventory.yml" 2>/dev/null || true
chmod 660 "$HUB_DIR/tokens/replay.db" 2>/dev/null || true
chmod 660 "$HUB_DIR/audit.jsonl" 2>/dev/null || true

# Lab join identity: generate once, publish pubkey for spokes to use when joining
JOIN_KEY="$HUB_DIR/keys/join_client"
if [ ! -f "$JOIN_KEY" ]; then
  ssh-keygen -t ed25519 -N "" -C "lab-join" -f "$JOIN_KEY" -q
fi
# Also place under /lab/keys if mounted writable — spokes read via docker network from hub file share
# Publish join pubkey into mcp-join authorized_keys (no ForceCommand override beyond Match User)
JOIN_PUB=$(cat "${JOIN_KEY}.pub")
AUTH=/home/mcp-join/.ssh/authorized_keys
# accept-join only via sshd Match ForceCommand
echo "$JOIN_PUB" >"$AUTH"
chmod 600 "$AUTH"
chown mcp-join:mcp-join "$AUTH" /home/mcp-join/.ssh

# Export join key material for enroll script (shared volume optional)
if [ -d /lab/keys ] && [ -w /lab/keys ]; then
  cp -f "$JOIN_KEY" /lab/keys/join_client
  cp -f "${JOIN_KEY}.pub" /lab/keys/join_client.pub
  cp -f "$HUB_DIR/keys/hub_client.pub" /lab/keys/hub_client.pub 2>/dev/null || true
  chmod 644 /lab/keys/*.pub 2>/dev/null || true
fi

# Ensure ansible_client can hop: copy hub_client to ansible_client if ansible empty — already separate keys
# For lab simplicity, also authorize hub ansible_client on spokes during enroll (enroll.sh installs hub_client)

echo "[hub] starting sshd; hub_id=$(cat "$HUB_DIR/hub_id")"
exec /usr/sbin/sshd -D -e
