# Installation

Source: private kit TheFLOW. Family ritual: clone DEVELOPMENT, then Compose.

This CORE branch is documentation only.

```sh
git clone -b DEVELOPMENT https://github.com/real-limitless/ansible-flow-mcp.git
cd ansible-flow-mcp
docker compose up -d --build
```

Hub MCP bridge: port 8789. The multi-spoke lab under `lab/` is extra, not the default install.

Host venv (`pip install -e .`) is for contributors. It is not the supported run path.
