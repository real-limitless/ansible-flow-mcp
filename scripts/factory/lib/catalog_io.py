"""Merge factory output into catalog/gallery.json + allowlist (locked)."""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

from .paths import ALLOWLIST, DEFAULT_DENY, GALLERY, JOBS, SCHEMAS

GALLERY_LOCK = JOBS / "gallery.lock"


@contextmanager
def _file_lock(lock_path: Path, *, timeout: float = 60.0) -> Iterator[None]:
    """Exclusive lock via O_EXCL lockfile (works across threads + processes)."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout
    fd: int | None = None
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()}\n".encode())
            break
        except FileExistsError:
            if time.time() >= deadline:
                # stale lock recovery
                try:
                    age = time.time() - lock_path.stat().st_mtime
                    if age > 120:
                        lock_path.unlink(missing_ok=True)
                        continue
                except Exception:
                    pass
                raise TimeoutError(f"gallery lock timeout: {lock_path}")
            time.sleep(0.05)
    try:
        yield
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _parse_gallery_text(raw: str) -> list[dict[str, Any]]:
    """Parse gallery JSON; recover from concurrent-write corruption."""
    raw = raw.strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict) and x.get("fqcn")]
        return []
    except json.JSONDecodeError:
        pass
    # take first complete JSON array
    start = raw.find("[")
    if start < 0:
        return []
    dec = json.JSONDecoder()
    try:
        data, _end = dec.raw_decode(raw[start:])
    except json.JSONDecodeError:
        # trim trailing garbage after last ]
        end = raw.rfind("]")
        if end > start:
            try:
                data = json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                return []
        else:
            return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict) and x.get("fqcn")]
    return []


def load_gallery(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or GALLERY
    if not p.is_file():
        return []
    return _parse_gallery_text(p.read_text(encoding="utf-8", errors="replace"))


def save_gallery(items: list[dict[str, Any]], path: Path | None = None) -> None:
    p = path or GALLERY
    # dedupe by fqcn
    by: dict[str, dict[str, Any]] = {}
    for x in items:
        if not isinstance(x, dict) or not x.get("fqcn"):
            continue
        fq = str(x["fqcn"])
        by[fq] = _slim_entry(x)
    ordered = sorted(by.values(), key=lambda x: str(x.get("fqcn") or ""))
    text = json.dumps(ordered, indent=2) + "\n"
    with _file_lock(GALLERY_LOCK):
        _atomic_write(p, text)


def _slim_entry(entry: dict[str, Any]) -> dict[str, Any]:
    fqcn = str(entry.get("fqcn") or "")
    return {
        "fqcn": fqcn,
        "shortName": str(entry.get("shortName") or fqcn.split(".")[-1]),
        "collection": str(
            entry.get("collection") or ".".join(fqcn.split(".")[:2]) if fqcn else ""
        ),
        "description": str(
            entry.get("description") or entry.get("shortName") or fqcn
        )[:500],
    }


def upsert_gallery_entry(
    entry: dict[str, Any],
    *,
    gallery_path: Path | None = None,
) -> None:
    fqcn = str(entry.get("fqcn") or "")
    if not fqcn:
        return
    p = gallery_path or GALLERY
    with _file_lock(GALLERY_LOCK):
        items = []
        if p.is_file():
            items = _parse_gallery_text(p.read_text(encoding="utf-8", errors="replace"))
        by = {str(x.get("fqcn")): x for x in items if isinstance(x, dict) and x.get("fqcn")}
        prev = by.get(fqcn) or {}
        merged = _slim_entry(
            {
                "fqcn": fqcn,
                "shortName": entry.get("shortName") or prev.get("shortName"),
                "collection": entry.get("collection") or prev.get("collection"),
                "description": entry.get("description") or prev.get("description"),
            }
        )
        by[fqcn] = merged
        ordered = sorted(by.values(), key=lambda x: str(x.get("fqcn") or ""))
        _atomic_write(p, json.dumps(ordered, indent=2) + "\n")


def repair_gallery(path: Path | None = None) -> int:
    """Rewrite gallery if corrupted. Returns entry count."""
    p = path or GALLERY
    items = load_gallery(p)
    save_gallery(items, p)
    return len(items)


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
    """Add collection to allowlist if missing. Preserves comments when possible."""
    if not collection:
        return False
    p = path or ALLOWLIST
    lock = JOBS / "allowlist.lock"
    with _file_lock(lock):
        if not p.is_file():
            if yaml is None:
                return False
            data = load_allowlist(p)
            data["collections"] = [collection]
            p.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(
                p, yaml.safe_dump(data, default_flow_style=False, sort_keys=False)
            )
            return True

        text = p.read_text(encoding="utf-8")
        if re.search(rf"(?m)^\s*-\s*{re.escape(collection)}\s*$", text):
            return False

        lines = text.splitlines(keepends=True)
        out: list[str] = []
        in_collections = False
        inserted = False
        last_item_idx = -1
        for line in lines:
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
            if yaml is None:
                return False
            data = load_allowlist(p)
            cols = sorted(set(list(data.get("collections") or []) + [collection]))
            data["collections"] = cols
            _atomic_write(
                p, yaml.safe_dump(data, default_flow_style=False, sort_keys=False)
            )
            return True

        _atomic_write(p, "".join(out))
        return True


def gallery_fqcns(path: Path | None = None) -> set[str]:
    return {str(x.get("fqcn")) for x in load_gallery(path) if x.get("fqcn")}


def schema_exists(fqcn: str, schemas_dir: Path | None = None) -> bool:
    d = schemas_dir or SCHEMAS
    return (d / f"{fqcn}.json").is_file()
