#!/usr/bin/env bash
# Build and start the test lab. Leaves it running (restart: unless-stopped).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib.sh
source "$ROOT/scripts/lib.sh"
cd "$ROOT"
compose up -d --build --remove-orphans --wait --wait-timeout "${AFM_TEST_WAIT_TIMEOUT:-600}"
echo "test lab is up (project ${AFM_PROJECT}). No host ports are published."
