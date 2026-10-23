#!/usr/bin/env bash
# Operator shell on the hub. Pass --tui for the curses UI (needs a TTY).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib.sh
source "$ROOT/scripts/lib.sh"
if [ "${1:-}" = "--tui" ]; then
  compose exec -it hub ansible-flow-mcp tui
else
  compose exec -it hub bash
fi
