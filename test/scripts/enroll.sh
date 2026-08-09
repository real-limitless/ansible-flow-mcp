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

  TOK_JSON=$(run_hub ansible-flow-mcp hub issue-token --name "$s" --ttl 15m)
  TOKEN=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])' <<<"$TOK_JSON")

  # Copy join private key into spoke for join SSH
  run_hub bash -lc "cat /var/lib/ansible-flow/hub/keys/join_client" \
    | run_spoke "$s" bash -lc 'cat > /tmp/join_client && chmod 600 /tmp/join_client'

  run_spoke "$s" bash -lc "
    set -e
    mkdir -p /home/mcp-spoke/.ssh /var/lib/ansible-flow/spoke/keys
    chown -R mcp-spoke:mcp-spoke /home/mcp-spoke /var/lib/ansible-flow/spoke
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
    # Also authorize ansible_client pubkey for Ansible SSH (same ForceCommand)
    if ! grep -q ansible-flow-ansible /home/mcp-spoke/.ssh/authorized_keys 2>/dev/null; then
      true
    fi
  "

  # Pull ansible_client.pub from hub and append with same ForceCommand
  APUB=$(run_hub bash -lc 'cat /var/lib/ansible-flow/hub/keys/ansible_client.pub')
  run_spoke "$s" bash -lc "
    FC='/usr/local/bin/ansible-flow-mcp spoke session'
    LINE=\"command=\\\"\$FC\\\",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty $APUB\"
    grep -q \"\$(echo '$APUB' | awk '{print \$NF}')\" /home/mcp-spoke/.ssh/authorized_keys 2>/dev/null \
      || echo \"\$LINE\" >> /home/mcp-spoke/.ssh/authorized_keys
    chown mcp-spoke:mcp-spoke /home/mcp-spoke/.ssh/authorized_keys
    chmod 600 /home/mcp-spoke/.ssh/authorized_keys
  "

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
