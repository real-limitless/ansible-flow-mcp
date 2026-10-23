#!/usr/bin/env bash
# Destroy volumes and enroll again. Requires --yes.
set -euo pipefail
if [ "${1:-}" != "--yes" ]; then
  echo "usage: $0 --yes" >&2
  echo "this deletes hub state, test keys, and join tokens" >&2
  exit 2
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/scripts/down.sh"
exec "$ROOT/scripts/bootstrap.sh"
