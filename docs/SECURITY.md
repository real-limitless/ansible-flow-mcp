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
4. Do not expose the MCP HTTP transport on the public internet without auth (HTTP MCP is out of scope for v1).
5. Keep `deny_modules` for free-form execution modules.
6. Hub **admin portal** (`ansible-flow-mcp hub admin`) is operator HTTP only: bind loopback by default, require `Authorization: Bearer` on `/v1/*`, never log join tokens or `admin.token`. Do not publish it on the public internet; tunnel if you need remote access.

## Admin portal

| Control | Behavior |
| --- | --- |
| Bind | `127.0.0.1:8788` unless overridden |
| Auth | `ANSIBLE_FLOW_ADMIN_TOKEN` or `$HUB_DIR/admin.token` |
| Surface | Inventory CRUD + audit; **no** `run_module` / `run_playbook` |
| Health | `/health` is unauthenticated and returns no secrets |
