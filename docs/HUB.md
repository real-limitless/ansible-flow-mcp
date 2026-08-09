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

Install sshd drop-ins from `examples/sshd/` (operator-managed).

## Runtime

```bash
# Agent / operator on hub
ansible-flow-mcp hub session   # MCP stdio with hub tools
ansible-flow-mcp hub status
ansible-flow-mcp hub spoke-call --node web-03 --tool list_collections
ansible-flow-mcp hub revoke --name web-03
```

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
| `list_nodes` / `hub_status` | Spokes + groups projection |
| `issue_token` / `revoke_node` / `update_node` | Membership |
| `list_groups` / `create_group` / `delete_group` / `set_group_members` | Targeting groups |
| `spoke_call` | SSH ForceCommand tool on a spoke |
| `search_modules` / `run_module` / … | Catalog + enrolled hosts **or** group names |

Inventory is fixed; client `-i` rejected in hub mode.

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
