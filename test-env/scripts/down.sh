#!/usr/bin/env bash
# Stop the test lab and delete its volumes (hub state, keys, tokens, spoke homes).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib.sh
source "$ROOT/scripts/lib.sh"
cd "$ROOT"
compose down -v --remove-orphans
echo "test lab removed, including volumes"
