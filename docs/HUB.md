# Hub/spoke deployment (issue #2)

Secure multi-host mode: **one hub** (agent entry + inventory source of truth) and **enrolled spokes** reached only over SSH.

## Roles

| Role | Agent attaches? | Execution |
| --- | --- | --- |
| **hub** | Yes | `localhost` + enrolled spokes |
| **spoke** | No | `localhost` only; hub SSH ForceCommand |

## Bootstrap

```bash
# On hub
sudo mkdir -p /var/lib/ansible-flow/hub
sudo chown "$USER" /var/lib/ansible-flow/hub
ansible-flow-mcp hub init --name ctrl-01

# Issue join token
ansible-flow-mcp hub issue-token --name web-03 --ttl 15m
# → print token once

# On spoke
ansible-flow-mcp spoke join \
  --token "$TOKEN" \
  --hub mcp-join@ctrl-01:22 \
  --public-addr web-03.example.com \
  --identity /path/to/join_client
```

Install sshd drop-ins from `examples/sshd/` (operator-managed).

## Runtime

```bash
# Agent / operator on hub
ansible-flow-mcp hub session   # MCP stdio with hub tools
ansible-flow-mcp hub status
ansible-flow-mcp hub spoke-call --node web-03 --tool list_collections
ansible-flow-mcp hub revoke --name web-03
```

Hub MCP tools: `list_nodes`, `hub_status`, `issue_token`, `revoke_node`, `spoke_call`, plus catalog/run tools with **fixed inventory**.

## Lab

See `test/README.md` and `test/docker-compose.yml` for a full hub + multi-OS spoke compose lab.

## Security properties

- Non-enrolled hosts cannot be targeted in hub mode
- Client-supplied `-i` inventory rejected in hub mode
- Host key checking on in hub/spoke mode
- Spokes cannot lateral-move via this fabric
- Join tokens: signed, TTL, one-time jti replay cache
