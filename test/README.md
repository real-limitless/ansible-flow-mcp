# Hub/spoke lab (`test/`)

Docker/Podman Compose lab for [issue #2](https://github.com/real-limitless/ansible-flow-mcp/issues/2): **1 hub + 3 spokes** (Debian ×2, Ubuntu).

## Quick start

```bash
cd test
./scripts/up.sh          # docker compose or podman compose
./scripts/enroll.sh      # issue-token + spoke join for each spoke
./scripts/smoke.sh       # spoke_call, no-shell, policy reject
```

## What it proves

| Check | How |
| --- | --- |
| Hub init | `entrypoint-hub.sh` → `ansible-flow-mcp hub init` |
| Join tokens | `hub issue-token` (TTL + one-time jti) |
| Spoke join | SSH `mcp-join@hub` ForceCommand → `hub accept-join` |
| ForceCommand | spoke `mcp-spoke` → `spoke session` (no shell) |
| `spoke_call` | hub SSH + simple-exec JSON (`list_collections`) |
| No unenrolled targets | policy rejects foreign hosts |
| OS matrix (default) | debian / ubuntu / debian |

## Layout

```text
test/
  docker-compose.yml
  images/          # Dockerfile.hub, Dockerfile.spoke, entrypoints, sshd
  scripts/         # up.sh enroll.sh smoke.sh
  keys/            # gitignored lab keys (optional bind)
```

## Manual commands

```bash
docker compose exec hub ansible-flow-mcp hub status
docker compose exec hub ansible-flow-mcp hub issue-token --name spoke-01 --ttl 10m
docker compose exec hub ansible-flow-mcp hub spoke-call --node spoke-01 --tool list_collections
docker compose exec hub ansible-flow-mcp hub revoke --name spoke-01
```

## Notes

- Agent attaches to **hub only** (stdio on hub host / `hub session`).
- Lab keys are throwaway; do not reuse in production.
- Rocky/Alpine images may take longer on first build (package managers).
