# Hub/spoke lab (`lab/`)

Docker/Podman Compose lab for hub/spoke: **1 hub + 3 spokes**, operator TUI, OpenCode + hub MCP, demo inventory/groups.

Full project walkthrough (install → lab → bare metal): **[docs/QUICKSTART.md](../docs/QUICKSTART.md)** (Path B).

## One-shot demo (recommended)

```bash
cd lab
./scripts/demo.sh
```

When run in a real terminal, **demo drops you into a shell on the hub** after smokes pass.

```bash
./scripts/demo.sh --no-shell   # setup only (CI)
./scripts/shell.sh             # hub shell anytime lab is up
./scripts/tui.sh               # operator TUI (inside hub)
./scripts/opencode.sh          # OpenCode *inside* hub container
./scripts/opencode-host.sh     # OpenCode *on your machine* → lab hub MCP (see spokes)
./scripts/reconnect.sh         # after hub rebuild: re-enroll + seed + refresh configs
```

## Manual lab (containers only — you enroll)

Spin up hub + spokes **without** enroll / seed / smoke. Practice invite, `spoke join`, and (optionally) Windows `register-target` yourself.

```bash
cd lab
./scripts/manual.sh                 # hub init done; no spokes enrolled
./scripts/manual.sh --blank         # wipe hub-data + true empty hub (no init/join keys)
./scripts/manual.sh --fresh         # wipe hub-data then up (hub still auto-inits)
./scripts/manual.sh --windows       # also start dockur guests (no register)
./scripts/manual.sh --no-shell      # CI / no hub shell
```

| Mode | Hub | Spokes | Windows targets |
| --- | --- | --- | --- |
| `manual.sh` | initialized + join channel | containers up, **not** joined | — |
| `manual.sh --blank` | **empty volume**, no `hub_id`, no join keys | same | — |
| `manual.sh --windows` | as above | as above | containers up, **not** registered |
| `demo.sh` | full auto fabric | enrolled + seeded + smoked | — |
| `demo-windows.sh` | full Linux if needed | enrolled | registered + smoked |

**`--blank` always wipes `hub-data`** (same as `--fresh`) so a previous demo cannot leave you “already configured.” After blank:

```bash
./scripts/shell.sh
# inside hub:
ansible-flow-mcp hub init --name hub-01
exit
ANSIBLE_FLOW_SKIP_HUB_INIT=0 ./scripts/up.sh   # install join keys + opencode
```

Then: `./scripts/tui.sh` → **i** invite, or CLI `hub issue-token` / `spoke join`.  
Targets: `./scripts/wait-windows.sh` then hand `register-target` or `./scripts/enroll-windows.sh`.

### After a hub rebuild, servers “disappear” in OpenCode?

Usually OpenCode on the **host** is still pointed at a local empty
`ANSIBLE_FLOW_HUB_DIR` (or a stale MCP process), not the compose hub volume.

**Fix:**

```bash
cd lab
./scripts/reconnect.sh
./scripts/opencode-host.sh
```

Then ask the agent: `hub_status` / `list_nodes` — you should see `spoke-01..03`
and groups `prod web app data edge batch canary`.

| Where you run OpenCode | Config | Inventory |
| --- | --- | --- |
| Host (`opencode-host.sh`) | `lab/opencode-hub.host.jsonc` → `hub-mcp.sh` | Lab hub container |
| Inside hub (`opencode.sh`) | `/var/lib/ansible-flow/hub/opencode-hub.jsonc` | Same lab volume |

Inside the hub shell:

```bash
ansible-flow-mcp hub status
ansible-flow-mcp tui
lab-opencode
ansible-flow-mcp hub spoke-call --node spoke-01 --tool list_collections
```

## Step by step

```bash
cd lab
./scripts/up.sh                 # containers only (same as manual without banner)
./scripts/manual.sh --no-shell  # up + banner; still no enroll
./scripts/enroll.sh             # join spokes + seed_demo groups
./scripts/smoke.sh
./scripts/smoke_tui_opencode.sh
```

## Demo inventory (after enroll/seed)

| Spoke | Role flavor | Groups |
| --- | --- | --- |
| `spoke-01` | web / edge (debian) | `web`, `edge`, `prod` |
| `spoke-02` | app / canary (ubuntu) | `app`, `canary`, `prod` |
| `spoke-03` | data / batch (debian) | `data`, `batch`, `prod` |

Groups: **prod web app data edge batch canary**

## What it proves

| Check | How |
| --- | --- |
| Hub init | entrypoint → `hub init` |
| Join tokens | `issue-token` + `spoke join` |
| ForceCommand | no shell on **mcp-spoke** SSH |
| Ansible shell | **mcp-ansible** + `ansible_client` (no ForceCommand) |
| `spoke_call` | hub → spoke simple-exec |
| `run_module` / ping | hub ansible → mcp-ansible (must not hang) |
| Groups | `seed_demo.sh` |
| OpenCode wiring | binary + `opencode-hub.jsonc` + `lab-opencode` |
| TUI module | import + config write (headless) |

## OpenCode in the hub

- Built into hub image when `INSTALL_OPENCODE=1` (default).
- Config: `/var/lib/ansible-flow/hub/opencode-hub.jsonc` (`hub write-opencode-config`).
- Wrapper: `lab-opencode` sets `OPENCODE_CONFIG` + hub env.
- Real chat needs provider API keys on the host, e.g.  
  `OPENCODE_API_KEY=… ./scripts/opencode.sh`  
  (compose passes `OPENCODE_API_KEY` through).

## Windows lab (opt-in, WinRM **targets**)

[dockur/windows](https://github.com/dockur/windows) guests: **Windows 11** (`win-client`) + **Server 2022** (`win-server`).  
They are **Ansible targets** (WinRM) — not mesh spokes. No `ansible-flow-mcp` on Windows. No `spoke_call`.

### Requirements

- Linux host with **KVM** (`/dev/kvm` r/w)
- ~8–16 GB free RAM, ~80+ GB disk
- First boot: ISO download + unattended install (**tens of minutes**)
- You must comply with **Microsoft licensing** (images are not shipped in this repo)

Not supported on Docker Desktop macOS / typical CI without nested virt.

### Commands

```bash
cd lab
cp windows/.env.example windows/.env   # optional overrides (gitignored)

./scripts/demo-windows.sh              # Linux fabric if needed + Windows path
# or step by step:
./scripts/up-windows.sh
./scripts/wait-windows.sh              # long poll for WinRM :5985
./scripts/enroll-windows.sh            # hub register-target + host_vars secrets
./scripts/smoke-windows.sh             # win_ping + spoke_call rejected
```

| Guest | SKU | Web UI | RDP (host) | Groups |
| --- | --- | --- | --- | --- |
| `win-client` | Win 11 | http://127.0.0.1:8006 | 3389 | `windows`, `win-clients` |
| `win-server` | Server 2022 | http://127.0.0.1:8007 | 3390 | `windows`, `win-servers` |

Default lab creds: user `Docker` / password `admin` (override via `windows/.env`).  
Passwords live in hub `host_vars/*.yml` (0600 on volume) — not in git or `hub status`.

OEM scripts under `windows/oem-*/` enable WinRM at first boot (`install.bat`).

Compose overlay: `docker-compose.windows.yml` (use with base `docker-compose.yml`).

## Layout

```text
lab/
  docker-compose.yml
  docker-compose.windows.yml   # opt-in dockur Win11 + Server2022
  images/          # Dockerfile.hub (+ OpenCode + pywinrm), spoke, entrypoints
  scripts/
    demo.sh manual.sh demo-windows.sh
    enroll.sh enroll-windows.sh seed_demo.sh
    smoke.sh smoke-windows.sh …
    up.sh up-windows.sh wait-windows.sh
  windows/         # oem-*, storage (gitignored), .env.example
  keys/            # gitignored
```

## Manual commands

```bash
docker compose exec hub ansible-flow-mcp hub status
docker compose exec -it hub ansible-flow-mcp tui
docker compose exec -it hub lab-opencode
docker compose exec hub ansible-flow-mcp hub write-opencode-config
```
