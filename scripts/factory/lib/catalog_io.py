"""Merge factory output into catalog/gallery.json + allowlist."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

from .paths import ALLOWLIST, DEFAULT_DENY, GALLERY, SCHEMAS


def load_gallery(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or GALLERY
    if not p.is_file():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def save_gallery(items: list[dict[str, Any]], path: Path | None = None) -> None:
    p = path or GALLERY
    p.parent.mkdir(parents=True, exist_ok=True)
    items = sorted(items, key=lambda x: str(x.get("fqcn") or ""))
    p.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")


def upsert_gallery_entry(
    entry: dict[str, Any],
    *,
    gallery_path: Path | None = None,
) -> None:
    fqcn = str(entry.get("fqcn") or "")
    if not fqcn:
        return
    items = load_gallery(gallery_path)
    by = {str(x.get("fqcn")): x for x in items if isinstance(x, dict)}
    prev = by.get(fqcn) or {}
    merged = {
        "fqcn": fqcn,
        "shortName": entry.get("shortName") or prev.get("shortName") or fqcn.split(".")[-1],
        "collection": entry.get("collection")
        or prev.get("collection")
        or ".".join(fqcn.split(".")[:2]),
        "description": entry.get("description")
        or prev.get("description")
        or entry.get("shortName")
        or fqcn,
    }
    # preserve optional ranking metadata when present
    for k in ("downloadCount", "collectionRank", "source"):
        if entry.get(k) is not None:
            merged[k] = entry[k]
        elif prev.get(k) is not None:
            merged[k] = prev[k]
    by[fqcn] = merged
    save_gallery(list(by.values()), gallery_path)


def load_allowlist(path: Path | None = None) -> dict[str, Any]:
    p = path or ALLOWLIST
    if yaml is None:
        raise RuntimeError("PyYAML required to update allowlist")
    if not p.is_file():
        return {
            "collections": [],
            "deny_modules": list(DEFAULT_DENY),
            "fqcn_pattern": r"^[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+$",
        }
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("collections", [])
    data.setdefault("deny_modules", list(DEFAULT_DENY))
    return data


def ensure_collection_allowlisted(
    collection: str,
    *,
    path: Path | None = None,
) -> bool:
    """Add collection to allowlist if missing. Returns True if changed.

    Prefers a surgical text insert under the ``collections:`` block so file
    comments are preserved; falls back to YAML dump only when needed.
    """
    if not collection:
        return False
    p = path or ALLOWLIST
    if not p.is_file():
        if yaml is None:
            return False
        data = load_allowlist(p)
        data["collections"] = [collection]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            yaml.safe_dump(data, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        return True

    text = p.read_text(encoding="utf-8")
    # already present as list item
    if re.search(rf"(?m)^\s*-\s*{re.escape(collection)}\s*$", text):
        return False

    lines = text.splitlines(keepends=True)
    out: list[str] = []
    in_collections = False
    inserted = False
    last_item_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^collections:\s*$", stripped):
            in_collections = True
            out.append(line)
            continue
        if in_collections:
            if stripped.startswith("- "):
                last_item_idx = len(out)
                out.append(line)
                continue
            if stripped == "" or stripped.startswith("#"):
                # end of list block once we leave items — insert before blank/comment after items
                if last_item_idx >= 0 and not inserted:
                    indent = "  "
                    # match indent of previous item
                    prev = out[last_item_idx]
                    m = re.match(r"^(\s*)-", prev)
                    if m:
                        indent = m.group(1)
                    out.insert(last_item_idx + 1, f"{indent}- {collection}\n")
                    # keep sorted-ish: actually re-sort collection lines
                    inserted = True
                in_collections = False
                out.append(line)
                continue
            # other key — close collections
            if last_item_idx >= 0 and not inserted:
                prev = out[last_item_idx]
                m = re.match(r"^(\s*)-", prev)
                indent = m.group(1) if m else "  "
                out.insert(last_item_idx + 1, f"{indent}- {collection}\n")
                inserted = True
            in_collections = False
            out.append(line)
            continue
        out.append(line)

    if in_collections and last_item_idx >= 0 and not inserted:
        prev = out[last_item_idx]
        m = re.match(r"^(\s*)-", prev)
        indent = m.group(1) if m else "  "
        out.insert(last_item_idx + 1, f"{indent}- {collection}\n")
        inserted = True

    if not inserted:
        # fallback structured write
        if yaml is None:
            return False
        data = load_allowlist(p)
        cols = sorted(set(list(data.get("collections") or []) + [collection]))
        data["collections"] = cols
        p.write_text(
            yaml.safe_dump(data, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        return True

    p.write_text("".join(out), encoding="utf-8")
    return True


def gallery_fqcns(path: Path | None = None) -> set[str]:
    return {str(x.get("fqcn")) for x in load_gallery(path) if x.get("fqcn")}


def schema_exists(fqcn: str, schemas_dir: Path | None = None) -> bool:
    d = schemas_dir or SCHEMAS
    return (d / f"{fqcn}.json").is_file()
