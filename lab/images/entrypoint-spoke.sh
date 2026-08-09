#!/bin/sh
set -eu

SPOKE_DIR="${ANSIBLE_FLOW_SPOKE_DIR:-/var/lib/ansible-flow/spoke}"
export ANSIBLE_FLOW_ROLE=spoke
export ANSIBLE_FLOW_SPOKE_DIR="$SPOKE_DIR"

mkdir -p "$SPOKE_DIR/keys" /var/run/sshd /home/mcp-spoke/.ssh
chmod 700 /home/mcp-spoke/.ssh "$SPOKE_DIR" || true

# Host keys
if [ ! -f /etc/ssh/ssh_host_ed25519_key ]; then
  ssh-keygen -A 2>/dev/null || true
fi

# Ensure mcp-spoke exists (bash shell + ForceCommand; unlocked for pubkey auth)
if ! id mcp-spoke >/dev/null 2>&1; then
  useradd -m -s /bin/bash mcp-spoke 2>/dev/null \
    || adduser -D -s /bin/sh mcp-spoke 2>/dev/null \
    || true
fi
usermod -s /bin/bash mcp-spoke 2>/dev/null || true
passwd -u mcp-spoke 2>/dev/null || usermod -p '*' mcp-spoke 2>/dev/null || true
chown -R mcp-spoke:mcp-spoke /home/mcp-spoke "$SPOKE_DIR" 2>/dev/null || true

# Empty authorized_keys until join
AUTH=/home/mcp-spoke/.ssh/authorized_keys
if [ ! -f "$AUTH" ]; then
  touch "$AUTH"
  chmod 600 "$AUTH"
  chown mcp-spoke:mcp-spoke "$AUTH" 2>/dev/null || true
fi

# sshd path differs
SSHD=$(command -v sshd || true)
if [ -z "$SSHD" ]; then
  for c in /usr/sbin/sshd /sbin/sshd; do
    [ -x "$c" ] && SSHD=$c && break
  done
fi

echo "[spoke ${SPOKE_NAME:-unknown}] starting sshd ($SSHD)"
exec "$SSHD" -D -e
