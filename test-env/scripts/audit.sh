#!/usr/bin/env bash
# Show the hub audit log (join tokens are not stored in it).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib.sh
source "$ROOT/scripts/lib.sh"
n="${1:-80}"
compose exec -T hub tail -n "$n" /var/lib/ansible-flow/hub/audit.jsonl
