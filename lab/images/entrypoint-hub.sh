#!/bin/bash
set -euo pipefail

HUB_DIR="${ANSIBLE_FLOW_HUB_DIR:-/var/lib/ansible-flow/hub}"
export ANSIBLE_FLOW_ROLE=hub
export ANSIBLE_FLOW_HUB_DIR="$HUB_DIR"

# When set (1/true/yes), skip hub init — for lab/scripts/manual.sh --blank
SKIP_INIT="${ANSIBLE_FLOW_SKIP_HUB_INIT:-0}"
case "${SKIP_INIT,,}" in
  1|true|yes|on) SKIP_INIT=1 ;;
  *) SKIP_INIT=0 ;;
esac

mkdir -p "$HUB_DIR" /var/run/sshd /home/mcp-join/.ssh
chmod 700 /home/mcp-join/.ssh

# Shared group so mcp-join (accept-join ForceCommand) can update inventory
groupadd -f ansible-flow 2>/dev/null || true
usermod -aG ansible-flow mcp-hub 2>/dev/null || true
usermod -aG ansible-flow mcp-join 2>/dev/null || true
usermod -s /bin/bash mcp-join 2>/dev/null || true
passwd -u mcp-join 2>/dev/null || usermod -p '*' mcp-join 2>/dev/null || true

# Host keys stay on the hub volume. The root filesystem may be read-only,
# so sshd reads a config under /run that points at those keys.
prepare_sshd() {
  local keydir="$1"
  mkdir -p "$keydir" /run/sshd
  if [ ! -s "$keydir/ssh_host_ed25519_key" ]; then
    ssh-keygen -q -t ed25519 -f "$keydir/ssh_host_ed25519_key" -N ""
  fi
  chown root:root "$keydir/ssh_host_ed25519_key" 2>/dev/null || true
  chmod 600 "$keydir/ssh_host_ed25519_key"
  # Globals before Include. Drop-ins end in Match, and Match must stay last.
  cat > /run/sshd/sshd_config <<EOF
HostKey ${keydir}/ssh_host_ed25519_key
PidFile /run/sshd.pid
AuthorizedKeysFile .ssh/authorized_keys ${keydir}/labadmin.authorized_keys
Include /etc/ssh/sshd_config.d/*.conf
EOF
}
prepare_sshd "$HUB_DIR/ssh"

hub_fix_perms() {
  chown -R mcp-hub:ansible-flow "$HUB_DIR" || chown -R mcp-hub:mcp-hub "$HUB_DIR" || true
  chmod -R g+rX "$HUB_DIR" || true
  chmod 775 "$HUB_DIR" 2>/dev/null || true
  [ -d "$HUB_DIR/tokens" ] && chmod 775 "$HUB_DIR/tokens" 2>/dev/null || true
  [ -d "$HUB_DIR/keys" ] && chmod 775 "$HUB_DIR/keys" 2>/dev/null || true
  [ -f "$HUB_DIR/hub_id" ] && chmod 664 "$HUB_DIR/hub_id" 2>/dev/null || true
  find "$HUB_DIR/keys" -type f ! -name '*.pub' -exec chmod 640 {} \; 2>/dev/null || true
  find "$HUB_DIR/keys" -name '*.pub' -exec chmod 644 {} \; 2>/dev/null || true
  find "$HUB_DIR/ca" -type f -exec chmod 640 {} \; 2>/dev/null || true
  chmod 660 "$HUB_DIR/known_hosts" 2>/dev/null || true
  chmod 660 "$HUB_DIR/inventory.yml" 2>/dev/null || true
  chmod 660 "$HUB_DIR/tokens/replay.db" 2>/dev/null || true
  chmod 660 "$HUB_DIR/audit.jsonl" 2>/dev/null || true
  chmod g+rw "$HUB_DIR/inventory.yml" "$HUB_DIR/known_hosts" "$HUB_DIR/tokens/replay.db" "$HUB_DIR/audit.jsonl" 2>/dev/null || true
  if [ -f "$HUB_DIR/admin.token" ]; then
    chmod 600 "$HUB_DIR/admin.token" 2>/dev/null || true
    chown mcp-hub:ansible-flow "$HUB_DIR/admin.token" 2>/dev/null || true
  fi
  # HTTP MCP bearer is root-only. Group read from the line above must not stick.
  if [ -f "$HUB_DIR/mcp.http.token" ]; then
    chmod 400 "$HUB_DIR/mcp.http.token" 2>/dev/null || true
    chown root:root "$HUB_DIR/mcp.http.token" 2>/dev/null || true
  fi
  if [ -d "$HUB_DIR/ssh" ]; then
    chown -R root:root "$HUB_DIR/ssh" 2>/dev/null || true
    chmod 700 "$HUB_DIR/ssh" 2>/dev/null || true
    chmod 600 "$HUB_DIR/ssh"/ssh_host_*_key 2>/dev/null || true
  fi
}

start_admin() {
  if [ ! -f "$HUB_DIR/hub_id" ]; then
    return 0
  fi
  # Container must listen on 0.0.0.0 so host 127.0.0.1:8789 publish works.
  local bind="${ANSIBLE_FLOW_ADMIN_BIND:-0.0.0.0}"
  local port="${ANSIBLE_FLOW_ADMIN_PORT:-8789}"
  if [ -f /var/run/ansible-flow-admin.pid ] && kill -0 "$(cat /var/run/ansible-flow-admin.pid)" 2>/dev/null; then
    echo "[hub] admin already running pid=$(cat /var/run/ansible-flow-admin.pid)"
    return 0
  fi
  nohup ansible-flow-mcp --hub-dir "$HUB_DIR" hub admin --host "$bind" --port "$port" \
    >>"$HUB_DIR/admin.log" 2>&1 &
  echo $! >/var/run/ansible-flow-admin.pid
  echo "[hub] admin console on ${bind}:${port}/admin/ (token file not printed)"
}

# Lab join identity + mcp-join authorized_keys
ensure_join_channel() {
  mkdir -p "$HUB_DIR/keys"
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
}

ensure_opencode_config() {
  case "${ANSIBLE_FLOW_SKIP_OPENCODE:-0}" in
    1|true|yes|on) return 0 ;;
  esac
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
  chmod 664 "$HUB_DIR/opencode-hub.jsonc" 2>/dev/null || true
}

if [ "$SKIP_INIT" = "1" ]; then
  # Truly blank: sshd + empty hub dir only. No hub init, join keys, or opencode.
  # (manual.sh --blank wipes hub-data so hub_id should not exist.)
  if [ -f "$HUB_DIR/hub_id" ]; then
    echo "[hub] WARNING: SKIP_HUB_INIT=1 but hub_id already exists on volume — not wiping."
    echo "[hub]          Use: ./scripts/manual.sh --fresh --blank"
    hub_fix_perms
    ensure_join_channel
    ensure_opencode_config
  else
    echo "[hub] BLANK mode: no hub init, no join channel, no opencode config"
    echo "[hub]   next: ansible-flow-mcp hub init --name hub-01"
    echo "[hub]   then:  compose restart hub   # installs join keys + opencode"
    mkdir -p "$HUB_DIR"
    # leave volume empty aside from the mount point
    chown mcp-hub:ansible-flow "$HUB_DIR" 2>/dev/null || true
    chmod 775 "$HUB_DIR" 2>/dev/null || true
    # empty mcp-join authorized_keys until post-init restart
    : >/home/mcp-join/.ssh/authorized_keys
    chmod 600 /home/mcp-join/.ssh/authorized_keys
    chown mcp-join:mcp-join /home/mcp-join/.ssh/authorized_keys
  fi
else
  if [ ! -f "$HUB_DIR/hub_id" ]; then
    ansible-flow-mcp hub init --name "${ANSIBLE_FLOW_HUB_NAME:-hub-01}"
  fi
  hub_fix_perms
  ensure_join_channel
  ensure_opencode_config
fi

HUB_ID_DISP="(not initialized)"
if [ -f "$HUB_DIR/hub_id" ]; then
  HUB_ID_DISP=$(cat "$HUB_DIR/hub_id" 2>/dev/null || echo "?")
fi
# labadmin is the operator shell (TUI). Key-only; unlock the account so OpenSSH accepts a pubkey.
if id labadmin >/dev/null 2>&1; then
  usermod -p '*' labadmin 2>/dev/null || true
  # Survives a read-only root and a tmpfs home. sshd allows this extra path.
  persist="$HUB_DIR/ssh/labadmin.authorized_keys"
  if [ ! -f "$persist" ]; then
    : >"$persist"
  fi
  chmod 600 "$persist"
  chown root:root "$persist" 2>/dev/null || true
  mkdir -p /home/labadmin/.ssh 2>/dev/null || true
  touch /home/labadmin/.ssh/authorized_keys 2>/dev/null || true
  chown -R labadmin:labadmin /home/labadmin/.ssh 2>/dev/null || true
  chmod 700 /home/labadmin/.ssh 2>/dev/null || true
  chmod 600 /home/labadmin/.ssh/authorized_keys 2>/dev/null || true
fi

supervise_loop() {
  local name="$1"
  shift
  (
    while true; do
      "$@" &
      echo $! >"/var/run/ansible-flow-${name}.pid"
      wait $! || true
      sleep 1
    done
  ) &
}

ensure_mcp_token() {
  local file="${ANSIBLE_FLOW_MCP_TOKEN_FILE:-$HUB_DIR/mcp.http.token}"
  if [ -n "${ANSIBLE_FLOW_MCP_TOKEN:-}" ]; then
    return 0
  fi
  export ANSIBLE_FLOW_MCP_TOKEN_FILE="$file"
  if [ -s "$file" ]; then
    chmod 400 "$file" 2>/dev/null || true
    return 0
  fi
  mkdir -p "$(dirname "$file")"
  python3 -c 'import os, pathlib, secrets, sys
p = pathlib.Path(sys.argv[1])
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(secrets.token_urlsafe(32) + "\n", encoding="utf-8")
os.chmod(p, 0o400)' "$file"
}

run_mcp_http() {
  ensure_mcp_token
  local bind="${ANSIBLE_FLOW_HTTP_HOST:-unspecified}"
  local port="${ANSIBLE_FLOW_HTTP_PORT:-8789}"
  exec ansible-flow-mcp --hub-dir "$HUB_DIR" hub mcp-http --host "$bind" --port "$port"
}

case "${ANSIBLE_FLOW_SUPERVISE_HTTP:-0}" in
  1|true|yes|on)
    admin_bind="${ANSIBLE_FLOW_ADMIN_BIND:-localhost}"
    admin_port="${ANSIBLE_FLOW_ADMIN_PORT:-8789}"
    supervise_loop admin ansible-flow-mcp --hub-dir "$HUB_DIR" hub admin --host "$admin_bind" --port "$admin_port"
    case "${ANSIBLE_FLOW_MCP_HTTP:-0}" in
      1|true|yes|on)
        supervise_loop mcp-http run_mcp_http
        ;;
    esac
    ;;
  *)
    start_admin || true
    ;;
esac

if [ -n "${ANSIBLE_FLOW_TEST_SPOKES:-}" ]; then
  nohup /usr/local/bin/hub-test-autojoin.sh >>"$HUB_DIR/autojoin.log" 2>&1 &
fi

echo "[hub] starting sshd; hub_id=$HUB_ID_DISP; skip_init=$SKIP_INIT; opencode=$(command -v opencode || echo missing)"
exec /usr/sbin/sshd -D -e -f /run/sshd/sshd_config
