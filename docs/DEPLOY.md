# Dev deployment

Single-node hub reachable over HTTPS. Agents attach to the hub only. The lab in `lab/` is still the multi-spoke integration suite. This profile does not start spokes, OpenCode, or sshd.

Public URL for the dev host: `https://ansible-flow-mcp.z.srl/mcp`

TLS terminates at Cloudflare, then Traefik. The container speaks HTTP on port 8789 and does not ship a certificate.

## What listens

| Path | Auth | Purpose |
| --- | --- | --- |
| `/health` and `/` | none | Liveness. No secrets. |
| `/mcp` | `Authorization: Bearer` | Streamable HTTP MCP (the agent API) |

Stdio is unchanged: `ansible-flow-mcp hub session`. The process refuses to listen on HTTP if the bearer is missing. An empty token is not an anonymous MCP port.

The bearer is an operator secret. It is not a spoke join token (`hub issue-token`) and not the admin portal token (`admin.token` / `ANSIBLE_FLOW_ADMIN_TOKEN`). `hub admin` is a separate loopback console and is not what this container runs.

## Environment

Set these in Dokploy (or a local `.env` that is not committed). Do not bake them into the image.

| Variable | Required | Meaning |
| --- | --- | --- |
| `ANSIBLE_FLOW_MCP_TOKEN` | yes, or the file below | Operator bearer for `/mcp` |
| `ANSIBLE_FLOW_MCP_TOKEN_FILE` | alternate | File with the bearer (Docker secret mount is fine) |
| `ANSIBLE_FLOW_PUBLIC_HOST` | no | Host header Traefik sends. Default `ansible-flow-mcp.z.srl` |
| `ANSIBLE_FLOW_HTTP_PORT` | no | Container port. Default `8789` |
| `ANSIBLE_FLOW_HUB_DIR` | no | Hub state. Default `/var/lib/ansible-flow/hub` (the volume) |
| `ANSIBLE_FLOW_HUB_NAME` | no | Name used on first `hub init`. Default `hub-01` |
| `ANSIBLE_FLOW_ROLE` | no | Compose sets `hub` |
| `ANSIBLE_FLOW_MCP_CLIENT_ID` | no | Audit client id when the request has no `X-Ansible-Flow-Client`. Default `operator` |
| `ANSIBLE_FLOW_MCP_MAX_SESSIONS` | no | Concurrent streamable sessions. Default `32` |
| `ANSIBLE_FLOW_MCP_RATE_PER_MINUTE` | no | Requests to `/mcp` per process. Default `120`. `0` disables |
| `ANSIBLE_FLOW_MCP_ALLOWED_HOSTS` | no | Extra Host values, comma-separated |
| `ANSIBLE_FLOW_MCP_ALLOWED_ORIGINS` | no | Extra Origin values. Absent Origin is allowed (server-side gateways) |
| `ANSIBLE_FLOW_TRAEFIK_ENTRYPOINT` | no | Default `websecure` |
| `ANSIBLE_FLOW_TRAEFIK_CERTRESOLVER` | no | Default `letsencrypt` |
| `DOKPLOY_NETWORK` | no | Existing Docker network Traefik already uses. Default `dokploy-network`. The Traefik overlay does not create it. |
| `ANSIBLE_FLOW_REQUIRE_CHECK` | no | If set, `check_mode=false` is refused. Same rule as stdio |

Check-then-apply, the collection allowlist, and the free-form module deny list apply to remote callers the same way they apply on stdio. Hub mode still rejects a client-supplied inventory (`-i`).

## Dokploy

1. Compose file: `docker-compose.yml` at the repo root, branch `DEVELOPMENT`.
2. Add `deploy/compose.traefik.yml` as a second compose file. It sets `networks: !override [dokploy-network]` (Docker Compose 2.24 or newer) so the service attaches only to the existing external network (`DOKPLOY_NETWORK`, default `dokploy-network`). Compose does not create a project default network. If the Dokploy UI only accepts one file, copy that service `networks` override and the top-level `networks` block into the compose it deploys. Do not also list `default`.
3. Set `ANSIBLE_FLOW_MCP_TOKEN` in the environment UI. Leave it out of git.
4. Domain `ansible-flow-mcp.z.srl`, container port `8789`. The compose labels already request that Host on the `websecure` entrypoint. If the Dokploy domain screen creates a second router for the same host, delete one of them.
5. One replica. Session state is in memory. A second replica will drop MCP sessions.
6. Do not set `container_name`. Do not publish 8789 on the host. Traefik reaches the exposed port on the Docker network.
7. Cloudflare: proxy the hostname, leave the `Authorization` header intact, and do not cache `/mcp`. If Cloudflare connects to Traefik on plain HTTP instead of `websecure`, set `ANSIBLE_FLOW_TRAEFIK_ENTRYPOINT=web` and turn the TLS label off.

Health check is `GET /health` inside the container. Dokploy should show the service healthy only after the bearer is set. Without the token the process exits and the check fails. That is intentional.

Traefik labels on the service (also in `docker-compose.yml`):

```yaml
labels:
  - traefik.enable=true
  - traefik.docker.network=dokploy-network
  - traefik.http.routers.ansible-flow-mcp.rule=Host(`ansible-flow-mcp.z.srl`)
  - traefik.http.routers.ansible-flow-mcp.entrypoints=websecure
  - traefik.http.routers.ansible-flow-mcp.tls=true
  - traefik.http.routers.ansible-flow-mcp.tls.certresolver=letsencrypt
  - traefik.http.services.ansible-flow-mcp.loadbalancer.server.port=8789
  - traefik.http.services.ansible-flow-mcp.loadbalancer.passhostheader=true
  - traefik.http.services.ansible-flow-mcp.loadbalancer.responseForwarding.flushInterval=100ms
```

`flushInterval` matters because streamable HTTP uses a server-sent stream. A buffering proxy will stall `initialize`.

## Laptop smoke (no Traefik)

Run the root `docker-compose.yml` alone. That file still uses Compose's project default network. Leave `deploy/compose.traefik.yml` off unless an external proxy network already exists.

```bash
export ANSIBLE_FLOW_MCP_TOKEN='choose-a-long-secret'
docker compose up -d --build
docker compose exec ansible-flow-mcp python3 -c \
  "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8789/health').read().decode())"
```

The root compose does not publish a host port. To hit it from the laptop, add a temporary `127.0.0.1:8789:8789` mapping. Do not publish `0.0.0.0`.

Unauthenticated `POST /mcp` returns 401. A correct bearer can `initialize`.

## Connect a client

Cursor (`examples/cursor-mcp-http.json`):

```json
{
  "mcpServers": {
    "ansible-flow": {
      "url": "https://ansible-flow-mcp.z.srl/mcp",
      "headers": {
        "Authorization": "Bearer REPLACE_ME"
      }
    }
  }
}
```

OpenCode (`examples/opencode-hub-http.jsonc`):

```jsonc
{
  "mcp": {
    "ansible-flow": {
      "type": "remote",
      "url": "https://ansible-flow-mcp.z.srl/mcp",
      "enabled": true,
      "headers": {
        "Authorization": "Bearer REPLACE_ME"
      }
    }
  }
}
```

Put the real bearer in the client config on the laptop, or in the client's secret store. Do not commit it. Optional header `X-Ansible-Flow-Client` shows up as `client_id` in `$HUB_DIR/audit.jsonl` (transport `http`). The bearer itself is never written there.

## SSH attach (no HTTP)

When the hub is reachable by SSH and you do not want a socket at all:

```jsonc
{
  "mcp": {
    "ansible-flow-hub": {
      "type": "local",
      "command": ["ssh", "-o", "BatchMode=yes", "ansible-flow@hub.example", "ansible-flow-mcp", "hub", "session"],
      "enabled": true
    }
  }
}
```

Host key checking stays on. This is the same stdio server, tunneled. See `examples/opencode-hub-ssh.jsonc`.

## Image

Root `Dockerfile`. Non-root user `ansible-flow` (uid 10001) after the entrypoint fixes volume ownership. `catalog/schemas` is copied. `ansible.posix` 1.6.2 is installed for the JSON callback. `openssh-client` is there so first boot can run `ssh-keygen` for the hub keys. There is no sshd in this image. No join tokens, private keys, or the MCP bearer are baked in. Hub keys are created on the volume at first start (`hub init`) and stay there across restarts.

Build locally:

```bash
docker build -t ansible-flow-mcp:local .
```

Publishing to a registry and a Helm chart are not part of this compose profile.

## Still true

- Spokes are not an agent entrypoint. HTTP MCP on `ANSIBLE_FLOW_ROLE=spoke` exits.
- Free-form modules stay denied. Check mode still defaults to true.
- Admin portal stays loopback and is a different token.
- One container. No multi-hub HA.
