# Quick start — full step-by-step

Get **ansible-flow-mcp** running end-to-end: install → MCP in your editor → optional hub/spoke lab or bare-metal fabric.

| Path | Time | What you get |
| --- | --- | --- |
| **[A. Local MCP](#path-a--local-mcp-single-node)** | ~10 min | Agent runs Ansible on **this machine** (dev / laptop) |
| **[B. Compose lab](#path-b--compose-lab-full-hubspoke)** | ~15–30 min | Hub + 3 spokes, TUI, OpenCode, demo groups |
| **[C. Bare-metal hub/spoke](#path-c--bare-metal-hubspoke)** | varies | Real hosts: enroll spokes, agent on hub only |

Read **[Security notes](#security-notes)** before production. Deep ops: [HUB.md](HUB.md) · [SECURITY.md](SECURITY.md) · lab: [lab/README.md](../lab/README.md).

---

## What this project is (30 seconds)

1. **MCP server** — AI agents call Ansible via tools: `search_modules` → `get_module_schema` → `run_module` / `run_playbook` (check mode default **on**).
2. **Hub/spoke fabric (optional)** — Agent attaches to the **hub only**. Spokes enroll with join tokens. Hub→spoke is **SSH**. Inventory is hub-owned; free-form `shell`/`command` modules are denied by default.

```text
  Editor / OpenCode
        │  MCP stdio
        ▼
   ┌─────────┐   SSH ForceCommand    ┌────────┐
   │   HUB   │ ───────────────────► │ spoke  │  (localhost Ansible only)
   └─────────┘                       └────────┘
   inventory SoT · issue tokens · groups · run_module to enrolled hosts
```

---

## Prerequisites

| Requirement | Local MCP (A) | Lab (B) | Bare metal (C) |
| --- | :---: | :---: | :---: |
| Python **≥ 3.11** | ✓ | on host optional* | ✓ on hub & spokes |
| `ansible-core` + **`ansible.posix`** | ✓ | inside images | ✓ |
| Git + clone of this repo | ✓ | ✓ | ✓ |
| Docker **or** Podman + Compose | | ✓ | |
| SSH between hub and spokes | | (compose network) | ✓ |
| Agent host (Cursor / Claude Desktop / OpenCode) | optional | optional | optional |

\* Lab images install Ansible inside containers; host only needs Compose (and OpenCode if you use host bridge).

### Install Ansible on a control node (A or C)

```bash
python3 -m pip install --user 'ansible-core>=2.16,<2.19'
export PATH="$HOME/.local/bin:$PATH"
ansible-galaxy collection install ansible.posix
# Plus any collections you will run (match catalog allowlist)
ansible --version
```

---

## Path A — Local MCP (single node)

Best first run: prove the agent loop on localhost before multi-host.

### A1. Clone and install

```bash
git clone https://github.com/real-limitless/ansible-flow-mcp.git
cd ansible-flow-mcp

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -U pip
pip install -e ".[dev]"
```

### A2. Sanity check

```bash
pytest -q
which ansible-flow-mcp
ansible-flow-mcp --help            # or: ansible-flow-mcp -h
```

### A3. Run the MCP server (stdio)

In a terminal (or leave this to your editor — see A4):

```bash
source .venv/bin/activate
ansible-flow-mcp
# Process waits on stdin — that is correct for MCP stdio.
# Stop with Ctrl-C when not attached to a client.
```

Legacy / no hub gates: plain `ansible-flow-mcp` with no hub state = **dev mode** (localhost / your inventory env).

### A4. Attach Cursor

1. Open Cursor MCP settings (or project `.cursor/mcp.json`).
2. Point at your venv binary (reliable) **or** use `uvx` like `examples/cursor-mcp.json`.

**Editable install (recommended while developing):**

```json
{
  "mcpServers": {
    "ansible-flow": {
      "command": "/ABS/PATH/ansible-flow-mcp/.venv/bin/ansible-flow-mcp",
      "env": {
        "ANSIBLE_FLOW_TIMEOUT": "120"
      }
    }
  }
}
```

**Published package via uvx** (`examples/cursor-mcp.json`):

```json
{
  "mcpServers": {
    "ansible-flow": {
      "command": "uvx",
      "args": ["--from", "ansible-flow-mcp", "ansible-flow-mcp"],
      "env": {
        "ANSIBLE_FLOW_TIMEOUT": "120"
      }
    }
  }
}
```

3. Restart MCP / reload Cursor. Confirm tools appear: `search_modules`, `get_module_schema`, `run_module`, `run_playbook`, `list_collections`.

### A5. Attach Claude Desktop

Merge `examples/claude-desktop.json` into Claude’s MCP config (path varies by OS), then fully quit and reopen Claude Desktop.

Use the same absolute venv `command` as Cursor if `uvx` is not on Claude’s PATH.

### A6. Attach OpenCode (local, non-hub)

```bash
# Example: local opencode config pointing at the CLI
# Prefer an absolute path to .venv/bin/ansible-flow-mcp
```

For **hub** OpenCode wiring see Path B and `examples/opencode-hub.jsonc`.

### A7. First agent ritual (modules)

Ask the agent (or call tools yourself):

1. **`search_modules`** — e.g. query `ping` or `file`
2. **`get_module_schema`** — FQCN from search (e.g. `ansible.builtin.ping`)
3. **`run_module`** — `check_mode=true` (default) on `localhost`
4. Only then apply with `check_mode=false` if your policy allows

Example intents:

- “Search for the ping module and run it in check mode on localhost.”
- “Show schema for `ansible.builtin.copy`, then dry-run a safe task.”

### A8. Optional env (local)

| Variable | Meaning |
| --- | --- |
| `ANSIBLE_FLOW_INVENTORY` | Default `-i` inventory (non-hub) |
| `ANSIBLE_FLOW_TIMEOUT` | Module timeout seconds (default 120) |
| `ANSIBLE_FLOW_PLAYBOOK_ROOTS` | Extra roots for `run_playbook` (`:`-separated) |
| `ANSIBLE_FLOW_REQUIRE_CHECK` | If set truthy, refuse `check_mode=false` |
| `ANSIBLE_FLOW_CATALOG_DIR` | Override packaged catalog |

---

## Path B — Compose lab (full hub/spoke)

Proves enrollment, ForceCommand, groups, TUI, and OpenCode against a real multi-host fabric **without** bare-metal SSH.

### B1. Requirements on the host

- Docker **or** Podman with Compose plugin  
- From repo root after clone (A1)

```bash
docker compose version    # or: podman compose version
cd lab
```

### B2. One-shot demo

```bash
./scripts/demo.sh
```

What it does:

1. `up.sh` — build/start hub + 3 spokes  
2. Wait for health  
3. `enroll.sh` — join tokens + `spoke join` for each spoke  
4. `seed_demo.sh` — groups: `prod web app data edge batch canary`  
5. `smoke.sh` + `smoke_tui_opencode.sh`  
6. Drops into a **hub shell** if you have a TTY  

Non-interactive / CI:

```bash
./scripts/demo.sh --no-shell
```

### B3. Demo inventory (after enroll)

| Spoke | Flavor | Groups |
| --- | --- | --- |
| `spoke-01` | web / edge (Debian) | `web`, `edge`, `prod` |
| `spoke-02` | app / canary (Ubuntu) | `app`, `canary`, `prod` |
| `spoke-03` | data / batch (Debian) | `data`, `batch`, `prod` |

### B4. Day-2 lab commands

```bash
cd lab

./scripts/shell.sh              # interactive shell on hub
./scripts/tui.sh                # operator TUI (needs TTY)
./scripts/opencode.sh           # OpenCode *inside* hub (needs API keys)
./scripts/opencode-host.sh      # OpenCode *on host* → lab hub via bridge

# Inside hub shell:
ansible-flow-mcp hub status
ansible-flow-mcp hub spoke-call --node spoke-01 --tool list_collections
ansible-flow-mcp tui
```

### B5. OpenCode: host vs inside hub

| Where OpenCode runs | How | Sees lab spokes? |
| --- | --- | --- |
| **Host** | `./scripts/opencode-host.sh` → `lab/opencode-hub.host.jsonc` + `hub-mcp.sh` | **Yes** |
| **Inside hub** | `./scripts/opencode.sh` / `lab-opencode` | **Yes** |
| Host with empty local `ANSIBLE_FLOW_HUB_DIR` | default local hub dir | **No** — looks like “no servers” |

After rebuilding the hub image:

```bash
cd lab
./scripts/reconnect.sh          # re-enroll + seed + refresh configs
./scripts/opencode-host.sh
```

Then ask the agent: `hub_status` / `list_nodes` — expect `spoke-01..03` and the seeded groups.

Provider keys for real chat (example):

```bash
OPENCODE_API_KEY=… ./scripts/opencode.sh
```

### B6. Manual practice (containers only)

Bring the lab up **without** auto enroll so you can invite/join yourself:

```bash
cd lab
./scripts/manual.sh                 # hub ready; spokes not joined
./scripts/manual.sh --blank         # you run hub init too
./scripts/manual.sh --fresh         # wipe hub-data first
./scripts/manual.sh --windows       # also start WinRM guests (not registered)
```

Then on the hub: TUI **i** invite (copy-paste `spoke join`), or CLI `hub issue-token` / `spoke join`.  
Windows targets: `wait-windows.sh` then hand `register-target` or `enroll-windows.sh`.

### B7. Step-by-step without `demo.sh`

```bash
cd lab
./scripts/up.sh
./scripts/enroll.sh
./scripts/seed_demo.sh
./scripts/smoke.sh
./scripts/smoke_tui_opencode.sh
```

### B8. Manual compose checks

```bash
cd lab
# docker or podman
docker compose exec -T hub ansible-flow-mcp hub status
docker compose exec -T hub ansible-flow-mcp hub spoke-call --node spoke-01 --tool list_collections
docker compose exec -T hub python3 -c \
  "from ansible_flow_mcp.catalog import get_module_schema; print(bool(get_module_schema('ansible.builtin.ping')))"
```

If `get_module_schema` is always `null`, the hub image is missing `catalog/schemas` — do not dockerignore that tree (see lab README).

### B9. Tear down

```bash
cd lab
docker compose down            # add -v to drop hub-data volume
```

### B10. Windows lab (opt-in WinRM targets)

Needs **KVM**, large disk, and a long first boot. Guests are **targets** (not mesh spokes).

```bash
cd lab
./scripts/demo-windows.sh
# or: up-windows.sh → wait-windows.sh → enroll-windows.sh → smoke-windows.sh
```

See [lab/README.md](../lab/README.md) § Windows lab. Plan notes on [#3](https://github.com/real-limitless/ansible-flow-mcp/issues/3).

---

## Path C — Bare-metal hub/spoke

Use when you have real machines. Operator installs package + sshd drop-ins; agent never attaches to spokes.

### C1. Install on hub and each spoke

```bash
# On every node (or package however you ship)
git clone https://github.com/real-limitless/ansible-flow-mcp.git
cd ansible-flow-mcp
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
# Ensure ansible-core + ansible.posix on hub (and spokes if they run modules locally)
```

Put `ansible-flow-mcp` on `PATH` for the service users you configure.

### C2. Initialize the hub

Default state dir is **user-writable** (`~/.local/share/ansible-flow/hub`) when
`/var/lib/ansible-flow/hub` is not available. No sudo required for a laptop/Pi trial.

```bash
# Simple (recommended first run)
ansible-flow-mcp hub init --name ctrl-01
ansible-flow-mcp hub status

# Production-style path (optional)
# sudo mkdir -p /var/lib/ansible-flow/hub
# sudo chown "$USER" /var/lib/ansible-flow/hub
# export ANSIBLE_FLOW_HUB_DIR=/var/lib/ansible-flow/hub
# ansible-flow-mcp hub init --name ctrl-01
```

### C3. Configure SSH (operator-managed)

Install drop-ins from `examples/sshd/` (see comments in those files and [HUB.md](HUB.md)):

| Identity | Typical user | Purpose |
| --- | --- | --- |
| **Mesh** (`hub_client`) | `mcp-spoke` + **ForceCommand** → `spoke session` | `spoke_call` only |
| **Ansible** (`ansible_client`) | shell-capable user (e.g. `mcp-ansible`) | `run_module` / ansible CLI |
| **Join** | `mcp-join` + ForceCommand → `hub accept-join` | Enrollment channel on hub |

**Critical:** do **not** put the Ansible key on a ForceCommand-only mesh user. Ansible expects a shell; ForceCommand starts MCP → hang, and the hub MCP session can block.

### C4. Enroll a spoke

**On hub** — issue a one-time join token:

```bash
export ANSIBLE_FLOW_HUB_DIR=/var/lib/ansible-flow/hub
ansible-flow-mcp hub issue-token --name web-03 --ttl 15m
# Copy the token once; it will not be shown again.
```

**On spoke:**

```bash
export ANSIBLE_FLOW_SPOKE_DIR=/var/lib/ansible-flow/spoke
sudo mkdir -p "$ANSIBLE_FLOW_SPOKE_DIR" && sudo chown "$USER" "$ANSIBLE_FLOW_SPOKE_DIR"

ansible-flow-mcp spoke join \
  --token "$TOKEN" \
  --hub mcp-join@ctrl-01.example.com:22 \
  --public-addr web-03.example.com
  # add --identity /path/to/key if your join user requires it

ansible-flow-mcp spoke status
```

**On hub** — confirm:

```bash
ansible-flow-mcp hub status
# or: ansible-flow-mcp hub list-nodes   # if exposed via CLI; else hub_status via MCP/TUI
```

### C5. Operator surfaces on hub

```bash
export ANSIBLE_FLOW_HUB_DIR=/var/lib/ansible-flow/hub

ansible-flow-mcp hub session          # MCP stdio for the agent (hub tools + catalog)
ansible-flow-mcp tui                  # servers · groups · invite · OpenCode
ansible-flow-mcp hub spoke-call --node web-03 --tool list_collections
ansible-flow-mcp hub write-opencode-config
ansible-flow-mcp hub revoke --name web-03
```

TUI keys (summary): servers / groups / hub views · invite · edit · revoke · **A** OpenCode · **q** quit. Needs a real TTY.

### C6. Point the agent at the hub only

OpenCode example (`examples/opencode-hub.jsonc`):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "ansible-flow-hub": {
      "type": "local",
      "command": ["ansible-flow-mcp", "hub", "session"],
      "enabled": true,
      "environment": {
        "ANSIBLE_FLOW_HUB_DIR": "/var/lib/ansible-flow/hub",
        "ANSIBLE_FLOW_ROLE": "hub"
      }
    }
  }
}
```

Cursor/Claude: same idea — `command` runs `ansible-flow-mcp hub session` with `ANSIBLE_FLOW_HUB_DIR` set. **Never** point the agent at `spoke session` as the entrypoint.

### C7. First multi-host agent ritual

1. `hub_status` / `list_nodes` — enrolled spokes **and** registered targets (`kind`)  
2. `list_groups` — targeting groups  
3. `search_modules` → `get_module_schema`  
4. `run_module` with `hosts` = spoke/target name or group, `check_mode=true`  
5. `spoke_call` for mesh simple-exec tools (spokes only — not WinRM targets)

Hub mode **rejects** client-supplied `-i` and unknown hosts.

### C8. Ansible targets (no agent on the box)

Windows, routers, and other hosts Ansible can reach **without** `ansible-flow-mcp`:

```bash
ansible-flow-mcp hub register-target \
  --name win-app-02 \
  --host 10.0.4.20 \
  --connection winrm \
  --user Administrator
```

- No join token; hub-side register only  
- `run_module` / groups work; **`spoke_call` does not**  
- Do not put passwords in CLI/MCP args — use hub Ansible config or secret path refs  
- See [HUB.md](HUB.md) and [issue #3](https://github.com/real-limitless/ansible-flow-mcp/issues/3)

---

## Agent ritual cheat sheet

| Goal | Tools / order |
| --- | --- |
| Discover module | `search_modules` → `get_module_schema` |
| Dry-run module | `run_module(..., check_mode=true)` |
| Apply module | `run_module(..., check_mode=false)` only after check |
| Playbook | Path under allowlisted roots → `run_playbook` check first |
| Fleet status | `hub_status` / `list_nodes` / `list_groups` |
| Mesh hop | `spoke_call` (not a substitute for Ansible become) |
| Membership | `issue_token` · `revoke_node` · `update_node` · group tools |

**Denied by default:** free-form `command` / `shell` / `raw` / `script`.

---

## Verify installation

```bash
# Package
python -c "import ansible_flow_mcp; print('ok')"
ansible-flow-mcp --help

# Unit tests (from repo)
pytest -q

# Catalog present (schemas ship in wheel/image)
python -c "from ansible_flow_mcp.catalog import get_module_schema; print(get_module_schema('ansible.builtin.ping') is not None)"

# Lab
cd lab && ./scripts/smoke.sh
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| MCP tools missing in editor | Wrong binary / PATH | Use absolute path to `.venv/bin/ansible-flow-mcp` |
| `get_module_schema` always null | Catalog schemas not installed/imaged | Rebuild wheel/image; do not ignore `catalog/schemas` |
| Lab OpenCode: no spokes | Pointing at empty **local** hub dir | `cd lab && ./scripts/opencode-host.sh` or `reconnect.sh` |
| After hub rebuild, inventory empty | Volume/enroll drift | `./scripts/reconnect.sh` |
| `run_module` / hub session hangs | Ansible key on ForceCommand mesh user | Split mesh vs ansible users ([HUB.md](HUB.md)) |
| Target host rejected | Not enrolled / wrong name | `hub_status`; enroll; use group or enrolled hostname |
| Join fails | Expired/reused token, SSH, perms | New `issue-token`; check `mcp-join` ForceCommand + hub dir perms |
| `check_mode=false` refused | `ANSIBLE_FLOW_REQUIRE_CHECK` set | Unset for apply, or keep check-only policy |

---

## Security notes

- Hub compromise ≈ classic Ansible control node — harden the bastion.  
- Spokes do not become agent entrypoints; no lateral MCP mesh.  
- Join tokens: short TTL, one-time; never log tokens or private keys.  
- Prefer check mode; keep free-form modules denied.  
- Details: [SECURITY.md](SECURITY.md).

---

## Where to go next

| Doc | Contents |
| --- | --- |
| [README.md](../README.md) | Product story, tools table, security summary |
| [HUB.md](HUB.md) | Hub/spoke deploy, dual SSH identities, TUI |
| [SECURITY.md](SECURITY.md) | Threat model and residual risk |
| [lab/README.md](../lab/README.md) | Compose scripts map and OpenCode wiring |
| [AGENTS.md](../AGENTS.md) | Layout and conventions for coding agents |
| `examples/` | Cursor, Claude Desktop, OpenCode, sshd drop-ins |

Issues: [github.com/real-limitless/ansible-flow-mcp/issues](https://github.com/real-limitless/ansible-flow-mcp/issues)
