#!/usr/bin/env bash
# Issue tokens on hub and join each spoke. Run after up.sh + healthy containers.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
  COMPOSE=(podman compose)
elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
else
  COMPOSE=(docker compose)
fi

run_hub() { "${COMPOSE[@]}" -f docker-compose.yml exec -T hub "$@"; }
run_spoke() {
  local name="$1"; shift
  "${COMPOSE[@]}" -f docker-compose.yml exec -T "$name" "$@"
}

echo "== hub status =="
run_hub ansible-flow-mcp hub status || run_hub ansible-flow-mcp hub init --name hub-01

# Ensure join key is in place on hub (entrypoint should have done this)
run_hub bash -lc 'test -f /var/lib/ansible-flow/hub/keys/join_client'

# Ensure mcp-join can read/write hub state (volume perms drift after rebuilds)
run_hub bash -lc '
  chown -R mcp-hub:ansible-flow /var/lib/ansible-flow/hub 2>/dev/null || true
  chmod -R g+rX /var/lib/ansible-flow/hub
  chmod 775 /var/lib/ansible-flow/hub /var/lib/ansible-flow/hub/tokens 2>/dev/null || true
  chmod 664 /var/lib/ansible-flow/hub/hub_id 2>/dev/null || true
  chmod 660 /var/lib/ansible-flow/hub/inventory.yml /var/lib/ansible-flow/hub/known_hosts /var/lib/ansible-flow/hub/tokens/replay.db 2>/dev/null || true
  usermod -aG ansible-flow mcp-join 2>/dev/null || true
'

SPOKES=(spoke-01 spoke-02 spoke-03)
for s in "${SPOKES[@]}"; do
  echo "== enroll $s =="
  # skip if container missing
  if ! "${COMPOSE[@]}" -f docker-compose.yml ps --status running -q "$s" >/dev/null 2>&1; then
    # older compose
    if ! "${COMPOSE[@]}" -f docker-compose.yml ps -q "$s" 2>/dev/null | grep -q .; then
      echo "skip $s (not running)"
      continue
    fi
  fi

  # Already enrolled? refresh known_hosts + repair ansible shell user keys
  ALREADY=$(run_hub python3 -c "import json,subprocess; s=json.loads(subprocess.check_output(['ansible-flow-mcp','hub','status'])); print('yes' if '$s' in (s.get('spokes') or []) else 'no')" 2>/dev/null || echo no)
  if [ "$ALREADY" = "yes" ]; then
    echo "  already enrolled — refreshing host key + mcp-ansible shell access"
    run_hub bash -lc "ssh-keyscan -p 22 $s 2>/dev/null >> /var/lib/ansible-flow/hub/known_hosts || true; chmod 660 /var/lib/ansible-flow/hub/known_hosts"
    APUB=$(run_hub bash -lc 'cat /var/lib/ansible-flow/hub/keys/ansible_client.pub')
    run_spoke "$s" bash -lc "
      set -e
      mkdir -p /home/mcp-ansible/.ssh
      id mcp-ansible >/dev/null 2>&1 || useradd -m -s /bin/bash mcp-ansible || adduser -D -s /bin/bash mcp-ansible
      AK=/home/mcp-ansible/.ssh/authorized_keys
      KEYBODY=\$(echo '$APUB' | awk '{print \$NF}')
      if [ -f \"\$AK\" ]; then grep -v \"\$KEYBODY\" \"\$AK\" > \"\$AK.tmp\" || true; mv \"\$AK.tmp\" \"\$AK\"; fi
      echo \"no-port-forwarding,no-X11-forwarding,no-agent-forwarding $APUB\" >> \"\$AK\"
      chown -R mcp-ansible:mcp-ansible /home/mcp-ansible
      chmod 700 /home/mcp-ansible/.ssh
      chmod 600 \"\$AK\"
      if [ -f /home/mcp-spoke/.ssh/authorized_keys ]; then
        grep -v \"\$KEYBODY\" /home/mcp-spoke/.ssh/authorized_keys > /tmp/mcp-spoke.ak || true
        mv /tmp/mcp-spoke.ak /home/mcp-spoke/.ssh/authorized_keys
        chown mcp-spoke:mcp-spoke /home/mcp-spoke/.ssh/authorized_keys
        chmod 600 /home/mcp-spoke/.ssh/authorized_keys
      fi
    "
    run_hub python3 -c "from ansible_flow_mcp.hub.enroll import update_node; print(update_node('$s', ansible_user='mcp-ansible'))"
    continue
  fi

  TOK_JSON=$(run_hub ansible-flow-mcp hub issue-token --name "$s" --ttl 15m)
  TOKEN=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])' <<<"$TOK_JSON")

  # Copy join private key into spoke for join SSH
  run_hub bash -lc "cat /var/lib/ansible-flow/hub/keys/join_client" \
    | run_spoke "$s" bash -lc 'cat > /tmp/join_client && chmod 600 /tmp/join_client'

  run_spoke "$s" bash -lc "
    set -e
    mkdir -p /home/mcp-spoke/.ssh /home/mcp-ansible/.ssh /var/lib/ansible-flow/spoke/keys
    chown -R mcp-spoke:mcp-spoke /home/mcp-spoke /var/lib/ansible-flow/spoke
    chown -R mcp-ansible:mcp-ansible /home/mcp-ansible
    chmod 700 /home/mcp-spoke/.ssh /home/mcp-ansible/.ssh
    ansible-flow-mcp spoke join \
      --token '$TOKEN' \
      --hub 'mcp-join@hub:22' \
      --public-addr '$s' \
      --name '$s' \
      --ssh-port 22 \
      --identity /tmp/join_client \
      --authorized-keys /home/mcp-spoke/.ssh/authorized_keys
    chown mcp-spoke:mcp-spoke /home/mcp-spoke/.ssh/authorized_keys
    chmod 600 /home/mcp-spoke/.ssh/authorized_keys
    # join installs ansible_client (no ForceCommand) on mcp-ansible when home exists
    if [ -f /home/mcp-ansible/.ssh/authorized_keys ]; then
      chown mcp-ansible:mcp-ansible /home/mcp-ansible/.ssh/authorized_keys
      chmod 600 /home/mcp-ansible/.ssh/authorized_keys
    fi
  "

  # Ensure ansible_client is on mcp-ansible WITHOUT ForceCommand (never on mcp-spoke)
  APUB=$(run_hub bash -lc 'cat /var/lib/ansible-flow/hub/keys/ansible_client.pub')
  run_spoke "$s" bash -lc "
    set -e
    mkdir -p /home/mcp-ansible/.ssh
    AK=/home/mcp-ansible/.ssh/authorized_keys
    KEYBODY=\$(echo '$APUB' | awk '{print \$NF}')
    # strip any prior copy of this key (including mistaken ForceCommand lines)
    if [ -f \"\$AK\" ]; then
      grep -v \"\$KEYBODY\" \"\$AK\" > \"\$AK.tmp\" || true
      mv \"\$AK.tmp\" \"\$AK\"
    fi
    echo \"no-port-forwarding,no-X11-forwarding,no-agent-forwarding $APUB\" >> \"\$AK\"
    chown -R mcp-ansible:mcp-ansible /home/mcp-ansible
    chmod 700 /home/mcp-ansible/.ssh
    chmod 600 \"\$AK\"
    # Remove ansible key from mcp-spoke if a previous lab put ForceCommand on it
    if [ -f /home/mcp-spoke/.ssh/authorized_keys ]; then
      grep -v \"\$KEYBODY\" /home/mcp-spoke/.ssh/authorized_keys > /tmp/mcp-spoke.ak || true
      mv /tmp/mcp-spoke.ak /home/mcp-spoke/.ssh/authorized_keys
      chown mcp-spoke:mcp-spoke /home/mcp-spoke/.ssh/authorized_keys
      chmod 600 /home/mcp-spoke/.ssh/authorized_keys
    fi
  "
  # Point inventory at shell user (never mcp-spoke — that is ForceCommand-only)
  run_hub python3 -c "from ansible_flow_mcp.hub.enroll import update_node; print(update_node('$s', ansible_user='mcp-ansible'))"

  # Capture spoke host key into hub known_hosts
  run_hub bash -lc "
    set -e
    ssh-keyscan -p 22 $s 2>/dev/null >> /var/lib/ansible-flow/hub/known_hosts || true
    chmod 600 /var/lib/ansible-flow/hub/known_hosts
  "
done

echo "== hub status after enroll =="
run_hub ansible-flow-mcp hub status

# Pretty demo groups + OpenCode config
if [ -x "$ROOT/scripts/seed_demo.sh" ]; then
  "$ROOT/scripts/seed_demo.sh"
fi
