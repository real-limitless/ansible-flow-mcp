from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any


def catalog_dir() -> Path:
    env = os.environ.get("ANSIBLE_FLOW_CATALOG_DIR")
    if env:
        return Path(env).expanduser().resolve()
    pkg = Path(__file__).resolve().parent / "catalog"
    if pkg.is_dir():
        return pkg
    return Path(__file__).resolve().parents[2] / "catalog"


@lru_cache(maxsize=1)
def load_gallery() -> list[dict[str, Any]]:
    path = catalog_dir() / "gallery.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict) and x.get("fqcn")]


def search_modules(query: str = "", *, limit: int = 25) -> list[dict[str, Any]]:
    q = (query or "").strip().lower()
    items = load_gallery()
    if not q:
        return items[: max(1, min(limit, 100))]
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in items:
        hay = " ".join(
            str(item.get(k, ""))
            for k in ("fqcn", "shortName", "collection", "description")
        ).lower()
        if q not in hay:
            continue
        score = 0
        fqcn = str(item.get("fqcn", "")).lower()
        short = str(item.get("shortName", "")).lower()
        if fqcn == q or short == q:
            score += 100
        elif fqcn.endswith("." + q) or short.startswith(q):
            score += 50
        elif q in fqcn:
            score += 25
        else:
            score += 10
        scored.append((score, item))
    scored.sort(key=lambda t: (-t[0], str(t[1].get("fqcn", ""))))
    return [x for _, x in scored[: max(1, min(limit, 100))]]


def get_module_schema(fqcn: str) -> dict[str, Any] | None:
    safe = fqcn.strip()
    path = catalog_dir() / "schemas" / f"{safe}.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def list_collections() -> list[str]:
    cols = sorted({str(x.get("collection", "")) for x in load_gallery() if x.get("collection")})
    return [c for c in cols if c]
