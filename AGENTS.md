# AGENTS.md — ansible-flow-mcp

Guidance for AI coding agents working in this repository.

## What this is

**ansible-flow-mcp** is an MCP server that exposes Ansible to AI agents, plus an optional **SSH hub/spoke** multi-host fabric:

| Layer | Purpose |
| --- | --- |
| **Core MCP** | `search_modules` → `get_module_schema` → `run_module` / `run_playbook` (check-first) |
| **Hub/spoke** ([issue #2](https://github.com/real-limitless/ansible-flow-mcp/issues/2)) | Agent attaches to **hub only**; spokes enroll with join tokens; hub→spoke is SSH only |
| **Operator TUI** | Curses UI on hub: servers/groups CRUD, invite tokens, launch OpenCode |
| **Compose lab** (`lab/`) | Full hub + 3 spokes, smoke scripts, OpenCode bridge from host |

Not affiliated with Red Hat/Ansible beyond the public CLI. Dual-tracked with [OpenFlow](https://github.com/real-limitless/OpenFlow) gallery concepts.

**Product docs:** `README.md`, `docs/QUICKSTART.md`, `docs/HUB.md`, `docs/SECURITY.md`, `lab/README.md`.

---

## Layout

```text
src/ansible_flow_mcp/
  cli.py           # entry: hub|spoke|tui|write-opencode-config|…
  server.py        # FastMCP tools; hub tools registered in hub mode
  runner.py        # ansible / ansible-playbook; hub inventory gates
  catalog.py       # gallery.json + catalog/schemas/*.json
  policy.py        # Role hub|spoke|legacy; enrolled hosts + groups
  security.py      # allowlist, redaction
  ssh.py           # spoke_call (ForceCommand simple-exec over SSH)
  tui.py           # operator TUI + write_opencode_hub_config
  paths.py         # ANSIBLE_FLOW_HUB_DIR / SPOKE_DIR defaults
  hub/
    state.py       # hub init, keys, signing, audit.jsonl
    tokens.py      # issue/verify join tokens (HMAC, jti replay)
    inventory.py   # inventory.yml, spokes, custom groups
    enroll.py      # accept_join, revoke, update_node, group ops
  spoke/
    join.py        # spoke join ceremony
    session.py     # ForceCommand: simple-exec or MCP stdio

catalog/           # MUST ship in wheel/image (do not dockerignore schemas/)
  collections-allowlist.yml
  gallery.json     # ~25k modules
  schemas/*.json   # arg schemas for get_module_schema

docs/
  HUB.md SECURITY.md campaign/ images/

site/                 # marketing site (GitHub Pages) + Schema Lab
  index|why|how|fabric|security|start.html
  assets/             # Copper Busbar CSS + lab.js gallery/schema UI

examples/
  cursor-mcp.json claude-desktop.json
  opencode-hub.jsonc          # in-process hub MCP for OpenCode
  sshd/ hub/                  # drop-ins + systemd examples

lab/                          # integration lab (compose), NOT pytest
  docker-compose.yml
  docker-compose.windows.yml  # opt-in dockur Windows (WinRM targets)
  windows/                    # oem WinRM scripts; storage gitignored
  images/                     # Dockerfile.hub|spoke, entrypoints, lab-opencode
  scripts/                    # demo, enroll, smoke, *-windows, tui, …
  README.md

tests/                        # unit tests (pytest)
  test_runner.py test_catalog.py
  test_hub_spoke.py test_hub_groups.py

scripts/                      # generate_catalog.py, factory/ (Galaxy scrape)
```

Package: `src/`. Console script: `ansible-flow-mcp` → `ansible_flow_mcp.cli:main`.  
Dependency pin: `mcp>=1.2.0,<2` (FastMCP lives in 1.x).

---

## Dev setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

- Python ≥ 3.11  
- `ansible-core` is a package dependency (`pip install` puts `ansible` on `PATH`)  
- Real runs also need Galaxy collection `ansible.posix` (JSON callback)  
- Unit tests mock the Ansible CLI  

---

## CLI surface

```bash
# Legacy / local dev MCP (no hub gates)
ansible-flow-mcp

# Hub
ansible-flow-mcp hub init --name hub-01
ansible-flow-mcp hub issue-token --name web-01 --ttl 15m
ansible-flow-mcp hub status
ansible-flow-mcp hub session              # MCP stdio + hub tools
ansible-flow-mcp hub tui                  # operator TUI
ansible-flow-mcp tui                      # same
ansible-flow-mcp hub write-opencode-config
ansible-flow-mcp hub spoke-call --node web-01 --tool list_collections
ansible-flow-mcp hub revoke --name web-01
ansible-flow-mcp hub register-target --name win-01 --host 10.0.4.20 --connection winrm
ansible-flow-mcp hub remove-target --name win-01
ansible-flow-mcp hub accept-join          # ForceCommand only

# Spoke
ansible-flow-mcp spoke join --token … --hub mcp-join@hub:22 --public-addr …
ansible-flow-mcp spoke session            # ForceCommand MCP / simple-exec
ansible-flow-mcp spoke status
```

Env:

| Variable | Meaning |
| --- | --- |
| `ANSIBLE_FLOW_HUB_DIR` | Hub state (default `/var/lib/ansible-flow/hub`) |
| `ANSIBLE_FLOW_SPOKE_DIR` | Spoke state |
| `ANSIBLE_FLOW_ROLE` | `hub` \| `spoke` (also auto-detected from state files) |
| `ANSIBLE_FLOW_CATALOG_DIR` | Override catalog root |
| `ANSIBLE_FLOW_REQUIRE_CHECK` | If truthy, refuse `check_mode=false` |
| `OPENCODE_CONFIG` | Path to OpenCode config (lab uses hub or host bridge file) |

---

## MCP tools

### Always (all modes)

| Tool | Notes |
| --- | --- |
| `search_modules` | Gallery substring search (`catalog.py`) — large gallery; keep results compact |
| `get_module_schema` | Reads `catalog/schemas/<fqcn>.json`; `null` if missing |
| `run_module` | Default `check_mode=true`; hub gates hosts/inventory |
| `run_playbook` | Path-jailed `.yml` |
| `list_collections` | From gallery |

### Hub mode only (`hub session` / `ANSIBLE_FLOW_ROLE=hub` + initialized hub)

| Tool | Notes |
| --- | --- |
| `list_nodes` / `hub_status` | Spokes + targets (`kind`) + groups |
| `issue_token` / `revoke_node` / `update_node` | Spoke membership |
| `register_target` / `update_target` / `remove_target` | Ansible-only targets (no agent; WinRM/SSH/…) |
| `list_groups` / `create_group` / `delete_group` / `set_group_members` | Groups (spokes and/or targets) |
| `spoke_call` | SSH ForceCommand simple-exec JSON to **mesh spoke** only |

### Spoke mode

- Localhost-only execution; no `issue_token` / foreign hosts.  
- ForceCommand often uses **simple-exec** one-shot JSON (`ansible_flow:1, op:call`), not full MCP framing — see `spoke/session.py` + `ssh.py`.

---

## Hub/spoke rules (do not regress)

1. Agent attaches to **hub only** — never make spokes the agent entrypoint.  
2. Hub inventory is source of truth — **reject client-supplied `-i`** in hub mode.  
3. Target only **enrolled spoke** or **registered target** names or **inventory group** names (+ localhost).  
4. Host key checking **on** in hub/spoke mode.  
5. Join tokens: signed, TTL, **one-time jti** replay cache.  
6. Free-form modules (`command`/`shell`/`raw`/`script`) **denied** by default.  
7. Playbooks path-jailed; subprocess **argv only** (no shell interpolation).  
8. Check mode default **true** on `run_module`.  
9. Never log join tokens, private keys, or secret module args.  
10. Groups cannot reference non-enrolled hosts; reserved: `all`, `hub`, `spokes`, `targets`, `ungrouped`.  
11. **Targets** (`ansible_flow_kind=target`) are Ansible-only (no join, no `spoke_call`); never store passwords in inventory/MCP args.

### Dual SSH identities (critical)

**Never conflate mesh MCP hop with Ansible shell.**

| Identity | Key (under hub `keys/`) | User on spoke | Purpose |
| --- | --- | --- | --- |
| Mesh / ForceCommand | `hub_client` | `mcp-spoke` + ForceCommand → `spoke session` | `spoke_call` only |
| Ansible | `ansible_client` | shell-capable user (lab may also ForceCommand for simplicity) | `run_module` SSH |

- `ssh.py` `spoke_call` must use **mesh** key + mesh user.  
- Lab enroll installs both pubs on `mcp-spoke` with ForceCommand for smoke simplicity; production should split users per `docs/HUB.md`.  
- Putting Ansible’s interactive expectations on a ForceCommand-only user deadlocks runs and can hang the hub MCP session.

Join channel on hub: user `mcp-join`, ForceCommand → `hub accept-join`.  
Hub volume perms: `mcp-join` in group `ansible-flow` must **read** `hub_id` and **write** inventory/tokens (see `lab/images/entrypoint-hub.sh` + enroll perm fixup).

---

## Operator TUI

```bash
ansible-flow-mcp tui
# keys: 1 servers  2 groups  3 hub  i invite  e edit  d revoke  g/m/x groups  A OpenCode  q quit
```

- Same inventory APIs as hub MCP tools (in-process).  
- **A** writes `$HUB_DIR/opencode-hub.jsonc` and launches `opencode` if on `PATH`.  
- Needs a real TTY (curses).

---

## Compose lab (`lab/`) — primary integration suite

**Not pytest.** Docker or Podman Compose. Full fabric + OpenCode wiring.

### One-shot

```bash
cd lab
./scripts/demo.sh              # up → enroll → seed → smoke → hub shell (if TTY)
./scripts/demo.sh --no-shell   # CI / non-interactive
./scripts/manual.sh            # up only — you enroll (TUI/CLI); --blank / --windows / --fresh
```

### After hub image rebuild (spokes “missing” in OpenCode)

```bash
cd lab
./scripts/reconnect.sh         # re-enroll + seed + refresh configs
./scripts/opencode-host.sh     # OpenCode on HOST → lab hub via bridge
```

### Script map

| Script | Purpose |
| --- | --- |
| `up.sh` | compose up --build |
| `manual.sh` | up only (no enroll/seed/smoke); `--blank` wipe volume + skip hub init/join/opencode; `--windows` dockur up; `--fresh` wipe volume; force-recreate |
| `enroll.sh` | issue-token + spoke join each spoke; calls `seed_demo.sh` |
| `seed_demo.sh` | groups: prod/web/app/data/edge/batch/canary + labels |
| `smoke.sh` | spoke_call, no shell leak, reject unenrolled host |
| `smoke_tui_opencode.sh` | opencode binary, config, seeded groups, APIs |
| `demo.sh` | full path + optional hub shell |
| `shell.sh` | interactive shell **on hub container** |
| `tui.sh` | TUI inside hub |
| `opencode.sh` | OpenCode **inside** hub (`lab-opencode`) |
| `opencode-host.sh` | OpenCode **on host** → `hub-mcp.sh` bridge |
| `hub-mcp.sh` | stdio MCP: `compose exec -T hub hub session` |
| `write-host-opencode-config.sh` | writes `lab/opencode-hub.host.jsonc` |
| `reconnect.sh` | rebuild recovery |
| `up-windows.sh` / `wait-windows.sh` / `enroll-windows.sh` / `smoke-windows.sh` / `demo-windows.sh` | Opt-in dockur Win11+Server2022 as **WinRM targets** (KVM) |

### Demo inventory (after seed)

| Spoke | Flavor | Groups |
| --- | --- | --- |
| `spoke-01` | web/edge (debian) | web, edge, prod |
| `spoke-02` | app/canary (ubuntu) | app, canary, prod |
| `spoke-03` | data/batch (debian) | data, batch, prod |

### OpenCode attachment (do not confuse)

| Where OpenCode runs | Config | Sees lab spokes? |
| --- | --- | --- |
| **Host** | `OPENCODE_CONFIG=lab/opencode-hub.host.jsonc` via `opencode-host.sh` | Yes (bridge into container volume) |
| **Inside hub** | `/var/lib/ansible-flow/hub/opencode-hub.jsonc` via `opencode.sh` | Yes |
| Host with default local `ANSIBLE_FLOW_HUB_DIR` empty | local empty hub | **No** — looks like “no servers” |

### Lab image pitfalls

1. **Never dockerignore `catalog/schemas`** — hub image must include schemas or `get_module_schema` returns null for everything (gallery alone is not enough).  
2. Hub build arg `INSTALL_OPENCODE=1` (default) installs OpenCode for lab AI.  
3. Editable install in image: code under `/opt/ansible-flow-mcp`; state under `/var/lib/ansible-flow/hub` (volume `hub-data`).  
4. After `compose build hub` + recreate, run **`reconnect.sh`** if inventory/joins drift or perms break `mcp-join`.

### Manual lab checks

```bash
cd lab
podman compose exec -T hub ansible-flow-mcp hub status
podman compose exec -T hub ansible-flow-mcp hub spoke-call --node spoke-01 --tool list_collections
podman compose exec -T hub python3 -c "from ansible_flow_mcp.catalog import get_module_schema; print(bool(get_module_schema('community.general.cloudflare_dns')))"
```

---

## Unit tests (`tests/`)

```bash
pytest -q
pytest tests/test_hub_spoke.py tests/test_hub_groups.py -q
```

| File | Covers |
| --- | --- |
| `test_runner.py` | argv, policy deny, mocked run |
| `test_catalog.py` | gallery/schema basics |
| `test_hub_spoke.py` | init, tokens, join, revoke, runner hub gates |
| `test_hub_groups.py` | groups CRUD, update_node, opencode config write |

Prefer **pytest green** before claiming done. Lab smokes are separate and slower.

---

## Commands cheat sheet

| Task | Command |
| --- | --- |
| Unit tests | `pytest -q` |
| Install editable | `pip install -e ".[dev]"` |
| Dev MCP | `ansible-flow-mcp` |
| Hub MCP | `ANSIBLE_FLOW_HUB_DIR=… ansible-flow-mcp hub session` |
| Lab full | `cd lab && ./scripts/demo.sh --no-shell` |
| Lab after rebuild | `cd lab && ./scripts/reconnect.sh` |
| Host OpenCode → lab | `cd lab && ./scripts/opencode-host.sh` |
| Regen catalog | `python scripts/generate_catalog.py` (needs `ansible-doc`) |
| Campaign PNGs | `cd docs/campaign && ./capture.sh` |

No dedicated lint/typecheck scripts yet. CI: `.github/workflows/ci.yml`.

---

## Conventions

- Python 3.11+; type hints where the file already uses them.  
- Concise style; few comments unless security/SSH non-obvious.  
- Prefer extending `hub/`, `spoke/`, `server.py`, `catalog.py` over new top-level packages.  
- Catalog allowlist: `catalog/collections-allowlist.yml`.  
- Runtime state **not in git**: hub/spoke dirs, `lab/keys/*`, `lab/opencode-hub.host.jsonc`.  
- Commit style when asked: `feat(hub):`, `fix(lab):`, `test(lab):`, `docs:`.  
- Feature branch for hub work: `feature/2-ssh-hub-spoke`.

---

## Docs & marketing

- Product story: `README.md` (campaign embeds under `docs/images/campaign-*.png`).  
- Generate PNGs: `docs/campaign/capture.sh` — do **not** reintroduce old OpenFlow `architecture.png` / `gallery-concept.png`.  
- Ops: `docs/HUB.md`. Security: `docs/SECURITY.md`. Lab: `lab/README.md`.

---

## Known gaps / next work (do not assume done)

- **search_modules** is linear substring over ~25k gallery entries; fine CPU-wise, but hub path can feel slow due to **compose exec + cold MCP process**. Planned: compact JSON, warm index, hybrid/synonym (RAG-like) search — not implemented until explicitly requested.  
- Full semantic embeddings optional later.  
- Production split of `mcp-spoke` vs Ansible shell user more strict than lab.  
- No multi-hub HA or public HTTP MCP in v1.  
- Ansible **targets** (WinRM/etc. without spoke agent): inventory + register API in progress ([#3](https://github.com/real-limitless/ansible-flow-mcp/issues/3)); TUI/creds hardening still open.

---

## Out of scope / non-goals (v1)

- Full-mesh hop plane; agent attach to arbitrary spokes  
- Full WinRM credential store / AWX-style plugins (path refs + hub Ansible cfg only for now)  
- Replacing AWX/Controller  
- Multi-hub HA  
- Public unauthenticated HTTP MCP  

---

## Git hygiene

- Do not commit secrets, `lab/keys/*` private material, hub/spoke private keys, join tokens.  
- Commit only when the user asks.  
- Never force-push protected branches unless asked.

---

## When stuck

1. Read `docs/HUB.md`, `docs/SECURITY.md`, `lab/README.md`.  
2. Trace: `cli.py` → `server.py` → `runner.py` / `hub/*` / `ssh.py` / `spoke/*`.  
3. Unit: `pytest tests/test_hub_spoke.py tests/test_hub_groups.py -q`.  
4. Lab: `cd lab && ./scripts/smoke.sh && ./scripts/smoke_tui_opencode.sh`.  
5. Empty servers in OpenCode: use `./scripts/opencode-host.sh` or `./scripts/reconnect.sh` — not a random local hub dir.  
6. Missing schemas in lab: ensure `.dockerignore` does **not** exclude `catalog/schemas`.  
7. Issues: [#2](https://github.com/real-limitless/ansible-flow-mcp/issues/2) hub/spoke, [#1](https://github.com/real-limitless/ansible-flow-mcp/issues/1) core MCP.
