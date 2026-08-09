#!/usr/bin/env bash
# Idempotent: pretty groups + labels on enrolled lab spokes.
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

echo "== seed demo inventory / groups =="
run_hub python3 - <<'PY'
from __future__ import annotations

from ansible_flow_mcp.hub.enroll import (
    create_group_op,
    hub_status,
    set_group_members_op,
    update_node,
)
from ansible_flow_mcp.hub.inventory import load_inventory, update_spoke, write_inventory
from ansible_flow_mcp.hub.state import load_hub_state
from ansible_flow_mcp.paths import hub_dir

st = load_hub_state(hub_dir())
status = hub_status(state=st)
spokes = set(status.get("spokes") or [])
need = {"spoke-01", "spoke-02", "spoke-03"}
missing = need - spokes
if missing:
    raise SystemExit(f"enroll spokes first; missing: {sorted(missing)}")

# Labels on inventory (extra fields)
inv = load_inventory(st.inventory_path)
meta = {
    "spoke-01": {
        "ansible_host": "spoke-01",
        "mesh_label": "web-edge",
        "mesh_os": "debian",
        "mesh_tier": "edge",
        "mesh_emoji": "🌐",
    },
    "spoke-02": {
        "ansible_host": "spoke-02",
        "mesh_label": "app-tier",
        "mesh_os": "ubuntu",
        "mesh_tier": "app",
        "mesh_emoji": "⚙️",
    },
    "spoke-03": {
        "ansible_host": "spoke-03",
        "mesh_label": "data-jobs",
        "mesh_os": "debian",
        "mesh_tier": "data",
        "mesh_emoji": "🗄️",
    },
}
for name, fields in meta.items():
    f = dict(fields)
    host = f.pop("ansible_host")
    update_spoke(inv, name, ansible_host=host, extra=f)
write_inventory(st.inventory_path, inv)

# Groups (idempotent create + set members)
groups = {
    "prod": ["spoke-01", "spoke-02", "spoke-03"],
    "web": ["spoke-01"],
    "app": ["spoke-02"],
    "data": ["spoke-03"],
    "edge": ["spoke-01"],
    "batch": ["spoke-03"],
    "canary": ["spoke-02"],
}
for gname, members in groups.items():
    try:
        create_group_op(gname, state=st)
    except ValueError as exc:
        if "already exists" not in str(exc):
            raise
    set_group_members_op(gname, members, state=st)

# OpenCode config
from ansible_flow_mcp.tui import App, write_opencode_hub_config

path = write_opencode_hub_config(App(hub_root=st.root, hub_ok=True))
final = hub_status(state=st)
print("nodes:", len(final.get("nodes") or []))
print("groups:", sorted(g["name"] for g in (final.get("groups") or [])))
print("opencode_config:", path)
print("SEED OK")
PY

echo ""
echo "Lab inventory ready:"
echo "  spoke-01  web/edge   groups: web, edge, prod"
echo "  spoke-02  app/canary groups: app, canary, prod"
echo "  spoke-03  data/batch groups: data, batch, prod"
echo "  groups:   prod web app data edge batch canary"
