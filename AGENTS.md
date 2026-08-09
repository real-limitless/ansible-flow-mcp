# AGENTS.md — ansible-flow-mcp

Guidance for AI coding agents working in this repository.

## What this is

**ansible-flow-mcp** is an MCP server that exposes Ansible to AI agents:

1. **Agent loop** — `search_modules` → `get_module_schema` → `run_module` / `run_playbook` (check-first)
2. **Hub/spoke fabric** ([issue #2](https://github.com/real-limitless/ansible-flow-mcp/issues/2)) — agent attaches to **hub only**; spokes enroll via join tokens; hub→spoke is SSH only

Not affiliated with Red Hat/Ansible beyond the public CLI. Dual-tracked with [OpenFlow](https://github.com/real-limitless/OpenFlow) gallery concepts.

## Layout

```text
src/ansible_flow_mcp/
  server.py      # MCP tools (stdio); hub vs spoke mode registration
  cli.py         # ansible-flow-mcp hub|spoke|tui|…
  runner.py      # ansible / ansible-playbook invocation
  catalog.py     # gallery + schemas
  policy.py      # allow/deny, hub targeting rules
  security.py    # redaction, path jail helpers
  ssh.py         # spoke_call (ForceCommand mesh SSH)
  tui.py         # operator TUI
  hub/           # init, tokens, inventory, enroll, groups
  spoke/         # join, spoke session
catalog/         # allowlist, gallery.json, schemas/ (shipped in wheel)
docs/
  HUB.md         # operator hub/spoke guide
  SECURITY.md    # trust boundary
  campaign/      # marketing storyboard HTML + capture.sh
  images/        # campaign-*.png for README
examples/        # MCP client configs, sshd drop-ins, hub systemd
test/            # docker/podman hub+spoke lab (not pytest)
tests/           # unit tests (pytest)
scripts/         # generate_catalog.py, factory/
```

Package lives under `src/`. Entry point: `ansible-flow-mcp` → `ansible_flow_mcp.cli:main`.

## Dev setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Requires Python ≥ 3.11. Real Ansible runs need `ansible-core` + `ansible.posix` on `PATH`; unit tests mock the CLI.

## Commands agents should run

| Task | Command |
| --- | --- |
| Unit tests | `pytest` |
| Single test file | `pytest tests/test_hub_spoke.py -q` |
| Install editable | `pip install -e ".[dev]"` |
| Run MCP (dev) | `ansible-flow-mcp` or `python -m ansible_flow_mcp.server` |
| Hub session | `ansible-flow-mcp hub session` |
| Lab demo | `cd test && ./scripts/demo.sh` |
| Lab smoke only | `cd test && ./scripts/up.sh && ./scripts/enroll.sh && ./scripts/smoke.sh` |
| Regen catalog | `python scripts/generate_catalog.py` (needs `ansible-doc`) |
| Campaign PNGs | `cd docs/campaign && ./capture.sh` |

No dedicated `lint` / `typecheck` scripts in-repo yet. Prefer `pytest` green before claiming done.

CI: `.github/workflows/ci.yml`.

## Critical design: dual SSH identities

**Never conflate mesh MCP hop with Ansible shell.**

| User | Key | Purpose |
| --- | --- | --- |
| `mcp-spoke` | `hub_client` + **ForceCommand** → `spoke session` | `spoke_call` only |
| `mcp-ansible` | `ansible_client`, **no** ForceCommand | `run_module` / ansible CLI |

- Inventory `ansible_user` = shell user (`mcp-ansible`)
- Inventory / code `mesh_user` = ForceCommand user (`mcp-spoke`)
- `ssh.py` `spoke_call` must target **mesh_user**, not `ansible_user`
- Putting `ansible_client` on `mcp-spoke` with ForceCommand deadlocks Ansible (expects `/bin/sh`, gets MCP) and can hang the hub MCP session

Details: `docs/HUB.md` § Spoke SSH users.

## Hub/spoke rules (do not regress)

- Agent attaches to **hub only**; spokes are not agent entrypoints
- Hub inventory is source of truth; **reject client-supplied `-i`** in hub mode
- Target only **enrolled** hosts/groups
- Host key checking **on** in hub/spoke mode
- Join tokens: signed, TTL, one-time jti replay cache
- Free-form modules (`command`/`shell`/`raw`/`script`) **denied** by default
- Playbooks path-jailed; CLI argv-only (no shell interpolation)
- Check mode default **true** on `run_module`
- Never log join tokens, private keys, or secret module args

## Conventions

- Python 3.11+, type hints where the surrounding file already uses them
- Match existing style: concise, few comments unless non-obvious security/SSH reasons
- Tests under `tests/`; lab integration under `test/` (compose scripts)
- Prefer editing existing modules over new top-level packages
- Catalog allowlist: `catalog/collections-allowlist.yml`
- State dirs (runtime, not in git): `/var/lib/ansible-flow/hub`, `…/spoke` (or `ANSIBLE_FLOW_HUB_DIR` / `ANSIBLE_FLOW_SPOKE_DIR`)

## Docs & marketing

- Product story: `README.md` (campaign embeds)
- Ops: `docs/HUB.md`, security: `docs/SECURITY.md`
- Visuals: `docs/images/campaign-*.png` from `docs/campaign/` — do **not** reintroduce old OpenFlow `architecture.png` / `gallery-concept.png`
- Lab operator notes: `test/README.md`

## Out of scope / non-goals (v1)

- Full-mesh hop plane, agent attach to arbitrary spokes
- WinRM / non-SSH Ansible in hub mode
- Replacing AWX/Controller
- Multi-hub HA
- Public unauthenticated HTTP MCP

## Git

- Do not commit secrets, lab keys under `test/keys/*`, or hub/spoke private key material
- Commit only when the user asks; match recent message style (`feat(hub):`, `fix(lab):`, `docs:`)
- Default feature branch for hub work has been `feature/2-ssh-hub-spoke`

## When stuck

1. Read `docs/HUB.md` and `docs/SECURITY.md`
2. Trace tools from `server.py` → `runner.py` / `hub/*` / `ssh.py`
3. Reproduce with `tests/test_hub_spoke.py` or `test/scripts/smoke.sh`
4. Issue plan: [#2](https://github.com/real-limitless/ansible-flow-mcp/issues/2) (hub/spoke), [#1](https://github.com/real-limitless/ansible-flow-mcp/issues/1) (core MCP)
