#!/bin/sh
set -eu

SPOKE_DIR="${ANSIBLE_FLOW_SPOKE_DIR:-/var/lib/ansible-flow/spoke}"
export ANSIBLE_FLOW_ROLE=spoke
export ANSIBLE_FLOW_SPOKE_DIR="$SPOKE_DIR"

mkdir -p "$SPOKE_DIR/keys" /var/run/sshd /home/mcp-spoke/.ssh
chmod 700 /home/mcp-spoke/.ssh "$SPOKE_DIR" || true

# Host keys stay on the spoke volume. /etc/ssh is read-only at runtime.
mkdir -p "$SPOKE_DIR/ssh" /run/sshd
if [ ! -s "$SPOKE_DIR/ssh/ssh_host_ed25519_key" ]; then
  ssh-keygen -q -t ed25519 -f "$SPOKE_DIR/ssh/ssh_host_ed25519_key" -N ""
fi
chmod 600 "$SPOKE_DIR/ssh/ssh_host_ed25519_key"
chown root:root "$SPOKE_DIR/ssh/ssh_host_ed25519_key" 2>/dev/null || true
# Globals before Include. Drop-ins end in Match, and Match must stay last.
cat > /run/sshd/sshd_config <<EOF
HostKey ${SPOKE_DIR}/ssh/ssh_host_ed25519_key
PidFile /run/sshd.pid
Include /etc/ssh/sshd_config.d/*.conf
EOF

# Ensure mcp-spoke exists (bash shell + ForceCommand; unlocked for pubkey auth)
if ! id mcp-spoke >/dev/null 2>&1; then
  useradd -m -s /bin/bash mcp-spoke 2>/dev/null \
    || adduser -D -s /bin/sh mcp-spoke 2>/dev/null \
    || true
fi
usermod -s /bin/bash mcp-spoke 2>/dev/null || true
passwd -u mcp-spoke 2>/dev/null || usermod -p '*' mcp-spoke 2>/dev/null || true
chown -R mcp-spoke:mcp-spoke /home/mcp-spoke "$SPOKE_DIR" 2>/dev/null || true
if [ -d "$SPOKE_DIR/ssh" ]; then
  chown -R root:root "$SPOKE_DIR/ssh" 2>/dev/null || true
  chmod 700 "$SPOKE_DIR/ssh" 2>/dev/null || true
  chmod 600 "$SPOKE_DIR/ssh"/ssh_host_*_key 2>/dev/null || true
fi

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

if id mcp-ansible >/dev/null 2>&1; then
  usermod -s /bin/bash mcp-ansible 2>/dev/null || true
  usermod -p '*' mcp-ansible 2>/dev/null || passwd -u mcp-ansible 2>/dev/null || true
  mkdir -p /home/mcp-ansible/.ssh
  chown -R mcp-ansible:mcp-ansible /home/mcp-ansible 2>/dev/null || true
  chmod 755 /home/mcp-ansible 2>/dev/null || true
  chmod 700 /home/mcp-ansible/.ssh 2>/dev/null || true
fi

case "${ANSIBLE_FLOW_AUTOJOIN:-0}" in
  1|true|yes|on)
    mkdir -p "$SPOKE_DIR"
    touch "$SPOKE_DIR/autojoin.log"
    chmod 600 "$SPOKE_DIR/autojoin.log" 2>/dev/null || true
    nohup /usr/local/bin/spoke-test-autojoin.sh >>"$SPOKE_DIR/autojoin.log" 2>&1 &
    ;;
esac

echo "[spoke ${SPOKE_NAME:-unknown}] starting sshd ($SSHD)"
exec "$SSHD" -D -e -f /run/sshd/sshd_config
