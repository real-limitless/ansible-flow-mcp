# Hub/spoke lab (`test/`)

Docker/Podman Compose lab for [issue #2](https://github.com/real-limitless/ansible-flow-mcp/issues/2): **1 hub + 3 spokes**, operator TUI, OpenCode + hub MCP, demo inventory/groups.

## One-shot demo (recommended)

```bash
cd test
./scripts/demo.sh
```

When run in a real terminal, **demo drops you into a shell on the hub** after smokes pass.

```bash
./scripts/demo.sh --no-shell   # setup only (CI)
./scripts/shell.sh             # hub shell anytime lab is up
./scripts/tui.sh               # operator TUI
./scripts/opencode.sh          # OpenCode + hub MCP
```

Inside the hub shell:

```bash
ansible-flow-mcp hub status
ansible-flow-mcp tui
lab-opencode
ansible-flow-mcp hub spoke-call --node spoke-01 --tool list_collections
```

## Step by step

```bash
cd test
./scripts/up.sh
./scripts/enroll.sh       # join spokes + seed_demo groups
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
| ForceCommand | no shell on spoke SSH |
| `spoke_call` | hub → spoke simple-exec |
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

## Layout

```text
test/
  docker-compose.yml
  images/          # Dockerfile.hub (+ OpenCode), spoke, entrypoints
  scripts/
    demo.sh enroll.sh seed_demo.sh smoke.sh smoke_tui_opencode.sh
    tui.sh opencode.sh up.sh
  keys/            # gitignored
```

## Manual commands

```bash
docker compose exec hub ansible-flow-mcp hub status
docker compose exec -it hub ansible-flow-mcp tui
docker compose exec -it hub lab-opencode
docker compose exec hub ansible-flow-mcp hub write-opencode-config
```
