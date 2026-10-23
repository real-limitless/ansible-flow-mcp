#!/usr/bin/env bash
# Revoke one enrolled spoke by inventory name. Does not delete the container.
set -euo pipefail
if [ -z "${1:-}" ]; then
  echo "usage: $0 <spoke-name>" >&2
  exit 2
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib.sh
source "$ROOT/scripts/lib.sh"
compose exec -T hub ansible-flow-mcp hub revoke --name "$1"
