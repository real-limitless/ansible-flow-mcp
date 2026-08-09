#!/bin/sh
set -eu
TINI="$(command -v tini 2>/dev/null || true)"
if [ -z "$TINI" ]; then
  for c in /usr/bin/tini /sbin/tini /usr/local/bin/tini; do
    if [ -x "$c" ]; then TINI=$c; break; fi
  done
fi
if [ -n "${TINI:-}" ]; then
  exec "$TINI" -- /usr/local/bin/entrypoint-spoke.sh
fi
exec /usr/local/bin/entrypoint-spoke.sh
