#!/usr/bin/env python3
"""Build chunked browse shards for Schema Lab (lazy load + worker search).

  python3 scripts/generate_browse.py
  GALLERY=catalog/gallery.json OUT=catalog/browse SHARD_SIZE=800 python3 scripts/generate_browse.py

Writes:
  catalog/browse/manifest.json
  catalog/browse/shard-000.json …
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GALLERY = Path(os.environ.get("GALLERY", ROOT / "catalog" / "gallery.json"))
OUT = Path(os.environ.get("OUT", ROOT / "catalog" / "browse"))
SHARD_SIZE = max(200, int(os.environ.get("SHARD_SIZE", "800")))


def slim_desc(s: str | None, max_len: int = 120) -> str:
    one = " ".join((s or "").split())
    if len(one) <= max_len:
        return one
    return one[: max_len - 1] + "…"


def main() -> int:
    if not GALLERY.is_file():
        print(f"missing gallery: {GALLERY}", file=sys.stderr)
        return 1

    data = json.loads(GALLERY.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        print("gallery.json must be a JSON array", file=sys.stderr)
        return 1

    rows: list[dict] = []
    collections: Counter[str] = Counter()
    for item in data:
        if not isinstance(item, dict):
            continue
        fqcn = str(item.get("fqcn") or "").strip()
        if not fqcn:
            continue
        col = str(item.get("collection") or "").strip()
        if col:
            collections[col] += 1
        short = str(item.get("shortName") or fqcn.split(".")[-1]).strip()
        rows.append(
            {
                "fqcn": fqcn,
                "shortName": short,
                "collection": col,
                "description": slim_desc(item.get("description")),
            }
        )

    rows.sort(key=lambda r: r["fqcn"].lower())

    if OUT.exists():
        for p in OUT.iterdir():
            if p.is_file():
                p.unlink()
    OUT.mkdir(parents=True, exist_ok=True)

    shards: list[str] = []
    if not rows:
        name = "shard-000.json"
        (OUT / name).write_text("[]\n", encoding="utf-8")
        shards.append(name)
    else:
        for i in range(0, len(rows), SHARD_SIZE):
            chunk = rows[i : i + SHARD_SIZE]
            name = f"shard-{len(shards):03d}.json"
            (OUT / name).write_text(
                json.dumps(chunk, ensure_ascii=False, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            shards.append(name)

    top_cols = [
        {"name": name, "count": count}
        for name, count in collections.most_common(80)
    ]

    manifest = {
        "version": 1,
        "updatedAt": __import__("datetime")
        .datetime.now(__import__("datetime").timezone.utc)
        .strftime("%Y-%m-%dT%H:%MZ"),
        "shardSize": SHARD_SIZE,
        "shardCount": len(shards),
        "total": len(rows),
        "shards": shards,
        "collections": top_cols,
        "fields": ["fqcn", "shortName", "collection", "description"],
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "out": str(OUT),
                "total": len(rows),
                "shards": len(shards),
                "shardSize": SHARD_SIZE,
                "collections": len(collections),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
