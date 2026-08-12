#!/usr/bin/env bash
# Build a local preview root: site/ + catalog/ (browse shards + schemas).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${SITE_PREVIEW_DIR:-$ROOT/.site-preview}"
PORT="${PORT:-8765}"

echo "Generating browse shards…"
python3 "$ROOT/scripts/generate_browse.py"

rm -rf "$OUT"
mkdir -p "$OUT/catalog"
cp -a "$ROOT/site/." "$OUT/"
# Keep gallery.json for MCP/tools fallback; site prefers browse/
if [[ -f "$ROOT/catalog/gallery.json" ]]; then
  cp -a "$ROOT/catalog/gallery.json" "$OUT/catalog/gallery.json"
fi
if [[ -d "$ROOT/catalog/browse" ]]; then
  cp -a "$ROOT/catalog/browse" "$OUT/catalog/browse"
fi
# Prefer hard link tree when possible; fall back to symlink (schemas are large).
if cp -al "$ROOT/catalog/schemas" "$OUT/catalog/schemas" 2>/dev/null; then
  :
else
  ln -sfn "$ROOT/catalog/schemas" "$OUT/catalog/schemas"
fi

echo "Preview root: $OUT"
echo "Open http://127.0.0.1:${PORT}/how.html  (Schema Lab)"
cd "$OUT"
exec python3 -m http.server "$PORT" --bind 127.0.0.1
