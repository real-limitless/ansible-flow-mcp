# Security model

ansible-flow-mcp runs the **local `ansible` CLI** on the machine hosting the MCP server. That host is the Ansible **control node**.

## Controls

| Control | Behavior |
| --- | --- |
| Collection allowlist | Only modules under configured collections |
| Module deny list | `command`, `shell`, `raw`, `script` denied by default |
| FQCN validation | Strict `a.b.c` pattern |
| No shell interpolation | `subprocess` argv list only |
| Check mode | Supported; agents should check before apply |
| Secret redaction | Common password/token keys redacted in results |
| Timeouts | Default 120s (env `ANSIBLE_FLOW_TIMEOUT`) |

## Trust boundary

Anyone who can call the MCP tools can change systems reachable with the control node’s Ansible credentials/inventory. Treat MCP access like SSH to your automation host.

## Hardening recommendations

1. Run under a dedicated OS user with limited sudo/become.
2. Pin inventory and disable broad `hosts: all` in agent prompts.
3. Prefer `check_mode=true` first in agent instructions.
4. HTTP MCP is opt-in (`ansible-flow-mcp serve`). It refuses to bind unless `ANSIBLE_FLOW_MCP_TOKEN` or `ANSIBLE_FLOW_MCP_TOKEN_FILE` is set. `/mcp` requires that bearer. `/health` is liveness only. Do not publish the container port on the public internet; put Cloudflare and Traefik in front. See [DEPLOY.md](DEPLOY.md).
5. Keep `deny_modules` for free-form execution modules.
6. Hub **admin portal** (`ansible-flow-mcp hub admin`) is operator HTTP only: bind loopback by default, require `Authorization: Bearer` on `/v1/*`, never log join tokens or `admin.token`. Do not publish it on the public internet; tunnel if you need remote access.

## Admin portal

| Control | Behavior |
| --- | --- |
| Bind | `127.0.0.1:8789` unless overridden |
| Auth | `ANSIBLE_FLOW_ADMIN_TOKEN` or `$HUB_DIR/admin.token` |
| Surface | Inventory CRUD + audit; **no** `run_module` / `run_playbook` |
| Health | `/health` is unauthenticated and returns no secrets |

## Remote MCP

Two ways to attach when the agent is not on the hub's stdin.

| Transport | How | Auth |
| --- | --- | --- |
| stdio (default) | `ansible-flow-mcp` or `hub session` | local user |
| SSH wrap | `ssh host ansible-flow-mcp hub session` | SSH host keys + that user. Example: `examples/opencode-hub-ssh.jsonc` |
| streamable HTTP | `POST /mcp` on `serve` | operator bearer. TLS is the proxy's job (Cloudflare + Traefik) |

The HTTP bearer is not a spoke join token and not `admin.token`. Rotating it is a restart with a new env value. Old copies stop working. `audit.jsonl` records `transport=http` and `client_id` (header `X-Ansible-Flow-Client` or `ANSIBLE_FLOW_MCP_CLIENT_ID`). It does not record the bearer, join tokens, or private keys.

In-process mutual TLS is not implemented. The dev host relies on the proxy certificate. Clients that pin a CA should pin the public certificate of the name in `ANSIBLE_FLOW_PUBLIC_HOST` (placeholder `mcp.example.com`).

### Threat model

- Stolen laptop token. Treat it like a bastion password. Rotate `ANSIBLE_FLOW_MCP_TOKEN` and restart. Prefer a client config that is not world-readable.
- Someone on the Docker network hits `:8789`. `/health` returns status only. `/mcp` still needs the bearer. The safety model (allowlist, free-form deny, check mode default, hub inventory) is the same code path as stdio.
- Confused deputy. A prompt can ask the agent to do damage the tools allow. Remote transport does not add a bypass and does not accept a client inventory file in hub mode.
- Proxy mistakes. Traefik must forward `Authorization` and the original `Host`. Do not log request headers. Do not cache `/mcp`. Buffering breaks the stream; the compose file sets a short Traefik flush interval.
- Session fan-out. Sessions live in the process. Run one replica. `ANSIBLE_FLOW_MCP_MAX_SESSIONS` (default 32) and `ANSIBLE_FLOW_MCP_RATE_PER_MINUTE` (default 120) cap a noisy client.
- Spoke as entrypoint. `serve` exits when `ANSIBLE_FLOW_ROLE=spoke`.
