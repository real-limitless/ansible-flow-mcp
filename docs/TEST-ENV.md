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

These are different credentials.

| Surface | Inside the lab | Token file (mode) |
| --- | --- | --- |
| Streamable HTTP MCP | `http://afm-test-hub:8790/mcp` | `/var/lib/ansible-flow/hub/mcp.http.token` (0400) |
| Admin portal | `http://afm-test-hub:8789/admin/` | `/var/lib/ansible-flow/hub/admin.token` (0600) |

`hub mcp-http` is opt-in in the product and **localhost by default**. This lab sets `ANSIBLE_FLOW_MCP_HTTP_BIND` and `ANSIBLE_FLOW_ADMIN_BIND` to the unspecified address so other containers on the private network can connect. Nothing maps those ports onto the host.

The bearer value is never passed in an environment variable (so `docker inspect` does not show it). Point `ANSIBLE_FLOW_MCP_TOKEN_FILE` at the file if you move it. Host allow-list for `/mcp` is `ANSIBLE_FLOW_MCP_ALLOWED_HOSTS` (container names, `localhost`, and `HUB_PUBLIC_HOST`, default `hub.example.com`).

Access log lines are JSON on stdout: `ts` (UTC), `service`, `environment`, `request_id`, `actor` (bearer key prefix only), `source_ip`, `action`, `outcome`. Tokens are not logged.

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

The admin portal is not MCP. Its own token is `admin.token`. `/health` on the admin port is the existing unauthenticated doctor and returns no tokens.

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

Unit tests cover token-file mode, the bearer gate, and the rendered compose (budget, no host ports, no public labels). Image builds are not in CI: five foreign bases plus the hub are not a cheap job, and CI must not publish this stack.

## Product notes

Streamable HTTP MCP was not in the tree before this lab. `docs/SECURITY.md` used to mark HTTP MCP out of scope. `hub mcp-http` is the opt-in listener the lab starts so a gateway can attach. Stdio `hub session` is unchanged. The default bind outside this compose file is localhost.

Spoke auto-join is enabled only when `ANSIBLE_FLOW_TEST_SPOKES` / `ANSIBLE_FLOW_AUTOJOIN` are set. The interactive `lab/` flow is still `scripts/enroll.sh`.
