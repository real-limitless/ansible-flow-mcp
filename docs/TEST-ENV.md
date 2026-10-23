# Test environment

Always-on private lab: one hub and one spoke per Linux flavor. An agent or MCP client talks only to the hub. Spokes are reached by the hub over SSH (ForceCommand), the same way the product works. This stack is separate from `lab/` (the interactive three-spoke lab) and from the single-node compose file at the repository root.

## What it is for

Use it to learn hub operations, attach an MCP gateway, and iterate. Smoke checks are connectivity only: the hub is up, each spoke is enrolled, hub-to-spoke SSH accepts a connection, `hub status` lists every flavor, and `hub spoke-call` runs `list_collections` on each spoke. It does not run playbooks.

## Flavor matrix

The only list of flavors is [`test-env/flavors.yml`](../test-env/flavors.yml). After editing it:

```bash
python3 test-env/scripts/render.py
```

That rewrites `test-env/docker-compose.yml`. Current flavors: Debian 12, Ubuntu 24.04, Rocky Linux 9, Fedora (floating `fedora:latest`), Alpine (floating `alpine:3`, latest 3.x). Pin those two tags in `flavors.yml` when you want a frozen build.

Rocky Linux 9's default Python is older than this package. The spoke image install script selects Python 3.11+ on that family.

## Isolation

| Item | Value |
| --- | --- |
| Compose project | `afm-test` |
| Network | `afm-test-net` (bridge, `internal: true`, no egress) |
| Volumes | named `afm-test-*` only |
| Hub id | created on first boot inside the hub volume (`hub init --name afm-test`) |
| Keys and tokens | generated at runtime on the volumes; never committed |
| Host ports | none (`ports` is not set) |
| Public proxy labels | none |

`internal: true` means the lab has no route to the public internet. Join, SSH, and HTTP stay on `afm-test-net`.

It does not publish the admin port, so it can run beside the single-node compose. The interactive `lab/` stack still publishes a loopback admin port; do not confuse the two.

Tear down, including volumes:

```bash
test-env/scripts/down.sh
# same as: docker compose --project-name afm-test -f test-env/docker-compose.yml down -v
```

## Memory

Limits live in `test-env/flavors.yml` and are copied into `mem_limit`, `memswap_limit` (same value, so swap cannot raise the cap), and `deploy.resources.limits.memory`.

| Container | Limit |
| --- | --- |
| hub | 640 MiB |
| each spoke (5) | 256 MiB |
| **total** | **1920 MiB** (budget 2048) |

`render.py` refuses a matrix whose sum exceeds `budget_mb`.

Images skip the OpenCode installer and Windows libraries (`INSTALL_OPENCODE=0`, `INSTALL_WINDOWS=0`). Spoke packages stay the ones `lab/images/install-spoke-deps.sh` already knows.

Measure with the runtime, not a guess:

```bash
test-env/scripts/measure.sh idle
test-env/scripts/measure.sh smoke
```

The script prints `docker stats` / `podman stats` and, for `smoke`, the peak it saw while `smoke.sh` ran. If neither runtime is available it exits 2 and says measurement is pending. Do not treat a limit as a measurement.

## Start and smoke

```bash
test-env/scripts/bootstrap.sh
```

That builds, waits for health, waits for enrollment, runs smoke, and leaves the stack up (`restart: unless-stopped`). Healthchecks cover sshd on every container, plus the hub admin `/health` and an anonymous `/mcp` status of 401.

Stepwise: `test-env/scripts/up.sh`, then `test-env/scripts/smoke.sh`.

## How spokes join

No join token is stored in git.

1. The hub entrypoint runs `hub init` once on the empty hub volume (new hub id, new keys).
2. It copies the join client key to a volume mounted read-only on every spoke.
3. For each name in `ANSIBLE_FLOW_TEST_SPOKES` that is not enrolled, it writes a one-time 15-minute token into that spoke's private drop volume (`/run/join-drop/<name>/token`, mode 0400). Other spokes do not mount that volume.
4. The spoke entrypoint runs `spoke join --token-file ...` against `mcp-join@hub:22`, then the hub deletes the token file.
5. When every flavor is enrolled, the hub ensures a group named `flavors` whose members are those spokes.
6. Spoke SSH host keys and authorized keys are on named volumes, so a recreate keeps the enrollment.

The auto-join log must not contain the token. `issue-token` output is captured and written to the drop file only.

## HTTP MCP and the admin portal

The lab uses the same streamable HTTP listener as `ansible-flow-mcp serve` (see [DEPLOY.md](DEPLOY.md) for the single-node profile). `hub mcp-http` calls that function. It does not start a second server. `/health` on that port is open. `/mcp` requires the operator bearer. Stdio `hub session` is unchanged.

This lab keeps the admin console on 8789 and sets `ANSIBLE_FLOW_HTTP_PORT` to 8790 so the two listeners do not share a port. The product default for `serve` remains 8789.

| Surface | Inside the lab | Credential |
| --- | --- | --- |
| Streamable HTTP MCP | `http://afm-test-hub:8790/mcp` | `ANSIBLE_FLOW_MCP_TOKEN` or `ANSIBLE_FLOW_MCP_TOKEN_FILE` |
| Admin portal | `http://afm-test-hub:8789/admin/` | `admin.token` (0600), separate from the MCP bearer |

The compose file does not set `ANSIBLE_FLOW_MCP_TOKEN`. On start the hub entrypoint creates `/var/lib/ansible-flow/hub/mcp.http.token` (mode 0400) when that file is missing and points `ANSIBLE_FLOW_MCP_TOKEN_FILE` at it. The value is not printed and is not an environment variable.

`ANSIBLE_FLOW_HTTP_HOST` and `ANSIBLE_FLOW_ADMIN_BIND` are the word `unspecified`. The process maps that word to the in-container any-address so other containers on the private network can connect. Nothing maps those ports onto the host.

Host allow-list is the product list (`localhost` and `ANSIBLE_FLOW_PUBLIC_HOST`) plus `ANSIBLE_FLOW_MCP_ALLOWED_HOSTS` (`afm-test-hub`, `hub`). Set `HUB_PUBLIC_HOST` when a proxy presents another name (placeholder `hub.example.com`). Session and rate caps are the product defaults: `ANSIBLE_FLOW_MCP_MAX_SESSIONS` (32) and `ANSIBLE_FLOW_MCP_RATE_PER_MINUTE` (120).

Accepted `/mcp` calls are recorded in `audit.jsonl` with `transport=http` and `client_id`. The bearer is not written there.

### Reach them from a private network

Keep the default compose as-is when you only use `docker exec`. To let a private proxy or an MCP gateway on another compose network reach the hub, attach the existing network. No public router labels are added:

```bash
AFM_TEST_ATTACH_PRIVATE_NET=1 \
AFM_TEST_EXTERNAL_NETWORK=private-network \
test-env/scripts/up.sh
```

`AFM_TEST_EXTERNAL_NETWORK` must already exist. Replace `private-network` with that network's name. Set `HUB_PUBLIC_HOST` if the proxy presents a different Host header (`hub.example.com` is the placeholder).

### Register the hub on an MCP gateway

Use placeholders in the gateway config. Put the secret in the gateway's secret store under a name. Do not paste the token into a ticket, a log, or git.

```text
MCP_GATEWAY_URL=https://gateway.example.com/mcp
HUB_PUBLIC_HOST=hub.example.com
```

| Gateway field | Value |
| --- | --- |
| Backend URL | `http://afm-test-hub:8790/mcp` on the private network, or `http://hub.example.com:8790/mcp` if the proxy serves that name |
| Header | `Authorization: Bearer <value of AFM_TEST_MCP_TOKEN>` |
| Secret | name only in git/config, for example `AFM_TEST_MCP_TOKEN`; the value is the contents of `mcp.http.token` |

The admin portal is not MCP. Its own token is `admin.token`. `/health` on the MCP port and on the admin port returns doctor JSON and no tokens. Unauthenticated `/mcp` returns 401.

## Shell and TUI

```bash
test-env/scripts/shell.sh
test-env/scripts/shell.sh --tui
```

`docker compose exec` is the normal path. The test image does not install OpenCode. The TUI still manages servers and groups; the OpenCode launch key has no binary here.

SSH as `labadmin` is key-only and only from a host that can already route to the hub on a private network (no host port). Install your own public key out of band; do not commit it:

```bash
docker compose --project-name afm-test -f test-env/docker-compose.yml exec -T hub \
  tee -a /home/labadmin/.ssh/authorized_keys >/dev/null
```

Then, from a machine on that private network: `ssh -p 22 labadmin@afm-test-hub`.

## Operations

**Add a spoke.** Add a row to `test-env/flavors.yml`, run `render.py`, then `test-env/scripts/up.sh`. The hub picks up `ANSIBLE_FLOW_TEST_SPOKES` and enrolls the new name.

**Remove a spoke.** `test-env/scripts/revoke.sh <name>`, delete the row, render, `up.sh` (so the service is dropped), then remove the leftover `afm-test-spoke-<name>` volumes if `up` did not.

**Rotate test tokens.** `test-env/scripts/rotate-tokens.sh`. It deletes both token files, restarts the listeners, and prints the paths. Copy the new MCP token into the gateway secret store yourself. Do not write the value down in the repo.

**Audit log.** `test-env/scripts/audit.sh`. File: `/var/lib/ansible-flow/hub/audit.jsonl`. Join token material is not written there (issue events store a `jti`, not the token).

**Revoke a spoke.** `test-env/scripts/revoke.sh <name>`. The container keeps running; it is no longer a target. Delete its drop token if you do not want auto-join to enroll it again (remove it from `flavors.yml` so the hub stops issuing a token).

**Reset.** `test-env/scripts/reset.sh --yes` runs `down -v` and bootstrap. That creates a new hub id and new keys.

## Compose platform

Point the platform at `test-env/docker-compose.yml` with the repository as the build context (the file's build `context` is the parent directory). Project name `afm-test`. Leave it running; `restart: unless-stopped` and the hub volume survive process restarts. A post-deploy command is only needed after a volume wipe: `test-env/scripts/bootstrap.sh`. Otherwise enrollment is already on the volumes.

Do not add public router labels and do not add a `ports:` mapping.

## Continuous integration

Unit tests cover the shared bearer gate and the rendered compose (budget, no host ports, no public labels). Image builds are not in CI: five foreign bases plus the hub are not a cheap job, and CI must not publish this stack.

## Product notes

HTTP MCP is `ansible-flow-mcp serve`, documented in [DEPLOY.md](DEPLOY.md) and [SECURITY.md](SECURITY.md). This lab starts that same listener with `hub mcp-http` and does not add a second implementation. It also does not add public proxy labels. Spoke auto-join is enabled only when `ANSIBLE_FLOW_TEST_SPOKES` / `ANSIBLE_FLOW_AUTOJOIN` are set. The interactive `lab/` flow is still `scripts/enroll.sh`.
