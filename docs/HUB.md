# Hub/spoke deployment

Secure multi-host mode: **one hub** (agent entry + inventory source of truth) and **enrolled spokes** reached only over SSH.

Product overview and campaign visuals: [README.md](../README.md) · storyboard [docs/campaign/](campaign/).  
**Step-by-step first run:** [QUICKSTART.md](QUICKSTART.md).

## Roles

| Role | Agent attaches? | Execution |
| --- | --- | --- |
| **hub** | Yes | `localhost` + enrolled spokes |
| **spoke** | No | `localhost` only; hub SSH ForceCommand |

## Bootstrap

```bash
# On hub — default state is user-writable:
#   ~/.local/share/ansible-flow/hub
# Optional production path:
#   sudo mkdir -p /var/lib/ansible-flow/hub && sudo chown "$USER" $_
#   export ANSIBLE_FLOW_HUB_DIR=/var/lib/ansible-flow/hub

ansible-flow-mcp hub init --name ctrl-01

# Issue join token
ansible-flow-mcp hub issue-token --name web-03 --ttl 15m
# → print token once

# On spoke
ansible-flow-mcp spoke join \
  --token "$TOKEN" \
  --hub mcp-join@ctrl-01:22 \
  --public-addr web-03.example.com \
  --identity /path/to/join_client
```

Install sshd drop-ins from `examples/sshd/` (operator-managed). The hub join Match User sets `ANSIBLE_FLOW_HUB_DIR` on ForceCommand so `mcp-join` does not fall back to an empty XDG hub dir. Keep `/var/lib/ansible-flow/hub` group-writable (`ansible-flow`, mode `0775`) and shared files (`inventory.yml`, `known_hosts`, `tokens/replay.db`) at `0660` so accept-join can update inventory after the first spoke.

## Runtime

```bash
# Agent / operator on hub
ansible-flow-mcp hub session   # MCP stdio with hub tools
ansible-flow-mcp hub status
ansible-flow-mcp hub spoke-call --node web-03 --tool list_collections
ansible-flow-mcp hub revoke --name web-03
ansible-flow-mcp hub admin     # operator web console (loopback)
```

### Operator admin portal

Same inventory APIs as the TUI and hub MCP tools, served as a Bearer-token web console (mcp-flow style). **Not** HTTP MCP — agents stay on `hub session` stdio.

```bash
ansible-flow-mcp hub admin
# alias: ansible-flow-mcp hub serve   (not the same as top-level `serve`)
# http://127.0.0.1:8789/admin/
```

- Default bind: `127.0.0.1:8789` (`$ANSIBLE_FLOW_ADMIN_BIND` / `$ANSIBLE_FLOW_ADMIN_PORT` or `--host` / `--port`)
- Token: `$ANSIBLE_FLOW_ADMIN_TOKEN` or `$HUB_DIR/admin.token` (created on `hub init`, mode `0600`). The CLI prints the **file path**, never the token.
- Paste the token once in the browser (stored in `sessionStorage`).
- Tabs: Status, Servers (invite / edit / revoke / ping), Targets, Groups, Audit
- `/health` is unauthenticated and returns the same doctor JSON as top-level `serve`
- Remote operators: SSH or Tailscale to the hub, then open loopback. Do not publish `:8789` on the public internet.
- Lab compose publishes `127.0.0.1:8789` on the host; inside the container the server binds `0.0.0.0`. Do not run the lab fabric and the root single-node compose at the same time (both want 8789).

### Operator TUI

```bash
ansible-flow-mcp tui
# or: ansible-flow-mcp hub tui --hub-dir /var/lib/ansible-flow/hub
```

- **Servers** — list enrolled spokes; invite (join token); edit host/port/user; revoke; ping  
- **Groups** — create/delete targeting groups; set members (enrolled spokes only)  
- **A** — write hub OpenCode MCP config and launch `opencode` with hub session  
- Static example: `examples/opencode-hub.jsonc`  
- Config helper: `ansible-flow-mcp hub write-opencode-config`

### Compose lab (TUI + OpenCode + demo inventory)

```bash
cd lab && ./scripts/demo.sh
./scripts/tui.sh          # interactive TUI on hub
./scripts/opencode.sh     # OpenCode with hub MCP
```

After enroll, `seed_demo.sh` creates groups `prod web app data edge batch canary` on the three lab spokes.

### Hub MCP tools (agent + TUI parity)

| Tool | Purpose |
| --- | --- |
| `list_nodes` / `hub_status` | Spokes + **targets** + groups (`kind` on each node) |
| `issue_token` / `revoke_node` / `update_node` | Spoke membership (join token / mesh) |
| `register_target` / `update_target` / `remove_target` | Ansible-only targets (WinRM/SSH/network — **no agent**) |
| `list_groups` / `create_group` / `delete_group` / `set_group_members` | Targeting groups (spokes and/or targets) |
| `spoke_call` | SSH ForceCommand tool on a **mesh spoke** only (not targets) |
| `search_modules` / `run_module` / … | Catalog + enrolled spoke/target names **or** group names |

Inventory is fixed; client `-i` rejected in hub mode.

### Spokes vs Ansible targets

| | **Spoke** | **Target** |
| --- | --- | --- |
| Install on machine | `ansible-flow-mcp` + `spoke join` | Nothing of ours |
| Ceremony | Join token (TTL, one-time) | Hub-side `register_target` |
| `spoke_call` | Yes | No |
| `run_module` | Yes | Yes (native `ansible_connection`) |
| Groups | Yes | Yes |

```bash
# Windows / device the hub can already reach with Ansible (no package on remote)
ansible-flow-mcp hub register-target \
  --name win-app-02 \
  --host 10.0.4.20 \
  --connection winrm \
  --user Administrator \
  --port 5986
# Creds: hub-side Ansible config or path refs — do not put passwords in --extra / MCP args
ansible-flow-mcp hub status
```

Plan: [issue #3](https://github.com/real-limitless/ansible-flow-mcp/issues/3).

### Lab: Windows WinRM targets (opt-in)

```bash
cd lab && ./scripts/demo-windows.sh
```

Uses [dockur/windows](https://github.com/dockur/windows) (KVM) for Win11 + Server 2022, OEM WinRM enablement, then `register-target`. See [lab/README.md](../lab/README.md).

## Lab

See `lab/README.md` and `lab/docker-compose.yml` for a full hub + multi-OS spoke compose lab.

## Spoke SSH users (critical)

| User | Key | Purpose |
| --- | --- | --- |
| **mcp-spoke** | `hub_client` + **ForceCommand** → `spoke session` | Mesh only (`spoke_call`) |
| **mcp-ansible** | `ansible_client`, **no** ForceCommand | Real shell for `run_module` / ansible CLI |

Do **not** put `ansible_client` on `mcp-spoke` with ForceCommand. Ansible opens SSH and expects `/bin/sh`; ForceCommand starts MCP instead → both sides wait forever. That blocks the hub stdio MCP session, so even `search_modules` times out.

## Security properties

- Non-enrolled hosts cannot be targeted in hub mode
- Client-supplied `-i` inventory rejected in hub mode
- Host key checking on in hub/spoke mode
- Spokes cannot lateral-move via this fabric
- Join tokens: signed, TTL, one-time jti replay cache
- Mesh user has no shell; ansible user is key-only (lab: passwordless sudo)
- Admin HTTP is operator-only (Bearer token, loopback by default); no public HTTP MCP
