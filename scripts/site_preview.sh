#!/usr/bin/env bash
# Build a local preview root: site/ + catalog/ (gallery + schemas).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${SITE_PREVIEW_DIR:-$ROOT/.site-preview}"
PORT="${PORT:-8765}"

rm -rf "$OUT"
mkdir -p "$OUT/catalog"
cp -a "$ROOT/site/." "$OUT/"
cp -a "$ROOT/catalog/gallery.json" "$OUT/catalog/gallery.json"
# Prefer hard link tree when possible; fall back to symlink (schemas ~67MB).
if cp -al "$ROOT/catalog/schemas" "$OUT/catalog/schemas" 2>/dev/null; then
  :
else
  ln -sfn "$ROOT/catalog/schemas" "$OUT/catalog/schemas"
fi

echo "Preview root: $OUT"
echo "Open http://127.0.0.1:${PORT}/  (Schema Lab needs this server, not file://)"
cd "$OUT"
exec python3 -m http.server "$PORT" --bind 127.0.0.1
