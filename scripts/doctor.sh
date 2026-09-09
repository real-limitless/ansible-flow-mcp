#!/usr/bin/env bash
set -euo pipefail
PORT="${ANSIBLE_FLOW_HTTP_PORT:-8789}"
if command -v ansible-flow-mcp >/dev/null 2>&1; then
  ansible-flow-mcp doctor
else
  curl -fsS "http://127.0.0.1:${PORT}/health"
  echo
fi
