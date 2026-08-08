# ansible-flow-mcp

MCP server that exposes **Ansible modules** to AI agents:

**search → schema → check → execute**

Dual-tracked with [OpenFlow](https://github.com/real-limitless/OpenFlow) Ansible canvas gallery  
([plan](https://github.com/real-limitless/ansible-flow-mcp/issues/1) · [OpenFlow umbrella](https://github.com/real-limitless/OpenFlow/issues/56)).

Not affiliated with Red Hat or the Ansible project beyond using the public Ansible CLI and docs.

## Requirements

- Python ≥ 3.11
- `ansible` / `ansible-core` on `PATH` for real runs (unit tests mock the CLI)
- Collections you intend to use installed on the control node

## Install (dev)

```bash
cd ansible-flow-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Run (stdio MCP)

```bash
ansible-flow-mcp
# or: python -m ansible_flow_mcp.server
```

### Cursor / Claude Desktop

See `examples/cursor-mcp.json` and `examples/claude-desktop.json`.

Local path example:

```json
{
  "mcpServers": {
    "ansible-flow": {
      "command": "/path/to/ansible-flow-mcp/.venv/bin/ansible-flow-mcp"
    }
  }
}
```

## Tools

| Tool | Purpose |
| --- | --- |
| `search_modules` | Gallery search |
| `get_module_schema` | Slim argSpec for FQCN |
| `run_module` | Ad-hoc ansible (`check_mode` default **true**) |
| `list_collections` | Collections in gallery |

### Agent ritual

1. `search_modules`  
2. `get_module_schema`  
3. `run_module(..., check_mode=true)`  
4. `run_module(..., check_mode=false)` if appropriate  

## Catalog

- `catalog/collections-allowlist.yml` — allowed collections + denied free-form modules  
- `catalog/gallery.json` — searchable module list  
- `catalog/schemas/*.json` — optional UI/agent schemas  

Regenerate when `ansible-doc` is available:

```bash
pip install pyyaml
python scripts/generate_catalog.py
```

## Env

| Variable | Meaning |
| --- | --- |
| `ANSIBLE_FLOW_CATALOG_DIR` | Override catalog path |
| `ANSIBLE_FLOW_COLLECTIONS` | Comma-separated collection allowlist override |
| `ANSIBLE_FLOW_INVENTORY` | Default `-i` inventory |
| `ANSIBLE_FLOW_TIMEOUT` | Seconds (default 120) |

## Security

See [docs/SECURITY.md](docs/SECURITY.md). Free-form modules (`command`/`shell`/`raw`/`script`) are **denied** by default.

## OpenFlow parity

Golden runner fixtures under `tests/fixtures/` define the shared result shape for OpenFlow’s `openflow-node-base.ansible` executor (TypeScript port).

## License

Apache-2.0

## Publish (PyPI)

```bash
pip install build twine
python -m build
# twine upload dist/*
```

Or from git:

```bash
uvx --from ansible-flow-mcp ansible-flow-mcp
```

Schemas cover the full committed gallery (builtin + popular collections). Regenerate with `scripts/generate_catalog.py` when `ansible-doc` is available.
