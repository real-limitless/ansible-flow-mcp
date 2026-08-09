"""Generate slim module schemas via ansible-doc (real options only when required)."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


def _loads_first_json(text: str) -> Any:
    """Parse first JSON value; tolerate trailing noise from ansible-doc."""
    text = (text or "").strip()
    if not text:
        raise json.JSONDecodeError("empty", text, 0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in "{[":
            data, _ = dec.raw_decode(text[i:])
            return data
    raise json.JSONDecodeError("no json", text, 0)


def _doc_usable(doc: dict[str, Any] | None) -> bool:
    """True if ansible-doc returned a real module payload (not {} / missing)."""
    if not doc or not isinstance(doc, dict):
        return False
    # empty object from missing collection
    if not doc:
        return False
    if isinstance(doc.get("doc"), dict):
        return True
    # already unwrapped-ish
    if "options" in doc or "short_description" in doc or "description" in doc:
        return True
    # single-key wrap handled by caller before this
    return False


def run_doc_json(
    fqcn: str,
    *,
    timeout: float = 60,
    env: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    try:
        out = subprocess.check_output(
            ["ansible-doc", "-j", fqcn],
            text=True,
            timeout=timeout,
            stderr=subprocess.DEVNULL,
            env=env or os.environ,
        )
        data = _loads_first_json(out)
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
        ValueError,
    ):
        return None
    if not isinstance(data, dict) or not data:
        return None
    if fqcn in data and isinstance(data[fqcn], dict):
        inner = data[fqcn]
        return inner if _doc_usable(inner) else None
    return data if _doc_usable(data) else None


def run_doc_list(
    *,
    timeout: float = 120,
    env: dict[str, str] | None = None,
) -> list[str] | None:
    try:
        out = subprocess.check_output(
            ["ansible-doc", "-l", "-j"],
            text=True,
            timeout=timeout,
            stderr=subprocess.DEVNULL,
            env=env or os.environ,
        )
        data = _loads_first_json(out)
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
        ValueError,
    ):
        return None
    if isinstance(data, dict):
        return sorted(str(k) for k in data.keys())
    return None


def normalize_schema(fqcn: str, doc: dict[str, Any]) -> dict[str, Any]:
    doc_root = doc.get("doc") if isinstance(doc.get("doc"), dict) else doc
    options_in = doc_root.get("options") if isinstance(doc_root, dict) else None
    options: list[dict[str, Any]] = []
    if isinstance(options_in, dict):
        for name, meta in options_in.items():
            if not isinstance(meta, dict):
                continue
            typ = meta.get("type") or "str"
            if typ in ("str", "path", "raw"):
                mapped = "string"
            elif typ in ("int", "float"):
                mapped = "number"
            elif typ == "bool":
                mapped = "boolean"
            elif typ == "list":
                mapped = "list"
            elif typ == "dict":
                mapped = "dict"
            else:
                mapped = "string"
            desc = meta.get("description")
            if isinstance(desc, list):
                desc = " ".join(str(x) for x in desc)
            options.append(
                {
                    "name": name,
                    "displayName": str(name).replace("_", " ").title(),
                    "type": mapped,
                    "required": bool(meta.get("required")),
                    "default": meta.get("default"),
                    "description": str(desc or "")[:500],
                    "choices": meta.get("choices")
                    if isinstance(meta.get("choices"), list)
                    else None,
                    "noLog": bool(meta.get("no_log")),
                    "suboptions": None,
                }
            )
    short = ""
    if isinstance(doc_root, dict):
        sd = doc_root.get("short_description") or doc_root.get("description") or ""
        if isinstance(sd, list):
            sd = " ".join(str(x) for x in sd)
        short = str(sd)[:300]
    parts = fqcn.replace(".", "/")
    return {
        "fqcn": fqcn,
        "shortDescription": short,
        "docUrl": f"https://docs.ansible.com/ansible/latest/collections/{parts}_module.html",
        "options": options,
        "source": "ansible-doc",
    }


def stub_schema(fqcn: str, description: str = "", *, source: str = "galaxy") -> dict[str, Any]:
    parts = fqcn.replace(".", "/")
    return {
        "fqcn": fqcn,
        "shortDescription": (description or fqcn.split(".")[-1])[:300],
        "docUrl": f"https://docs.ansible.com/ansible/latest/collections/{parts}_module.html",
        "options": [],
        "source": source,
    }


class SchemaUnavailable(RuntimeError):
    """Raised when require_real and ansible-doc cannot produce a module schema."""


def generate_schema(
    fqcn: str,
    *,
    description: str = "",
    prefer_ansible_doc: bool = True,
    require_real: bool = True,
    env: dict[str, str] | None = None,
) -> tuple[dict[str, Any], str]:
    """Return (schema, method).

    method is ``ansible-doc`` or ``stub``.
    When require_real=True and ansible-doc misses, raises SchemaUnavailable
    (does not write galaxy-stub).
    """
    if prefer_ansible_doc:
        doc = run_doc_json(fqcn, env=env)
        if doc:
            return normalize_schema(fqcn, doc), "ansible-doc"
    if require_real:
        raise SchemaUnavailable(
            f"ansible-doc has no usable schema for {fqcn} "
            f"(collection missing or module not found)"
        )
    return stub_schema(fqcn, description, source="galaxy-stub"), "stub"


def write_schema(
    schema: dict[str, Any],
    schemas_dir: Path,
    *,
    overwrite_richer: bool = False,
) -> Path:
    """Write schema. Refuses to replace a non-empty options schema with a stub."""
    schemas_dir.mkdir(parents=True, exist_ok=True)
    fqcn = str(schema.get("fqcn") or "unknown")
    path = schemas_dir / f"{fqcn}.json"
    src = str(schema.get("source") or "")
    if src in ("galaxy-stub", "stub", "galaxy") and not overwrite_richer:
        # never persist stubs when a real file already exists
        if path.is_file():
            try:
                prev = json.loads(path.read_text(encoding="utf-8"))
                if prev.get("source") == "ansible-doc":
                    return path
            except Exception:
                pass
    if path.is_file() and not overwrite_richer:
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            prev_opts = prev.get("options") if isinstance(prev, dict) else None
            new_opts = schema.get("options") or []
            if isinstance(prev_opts, list) and len(prev_opts) > 0 and len(new_opts) == 0:
                return path
        except Exception:
            pass
    path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    return path


def builtin_modules_from_doc(
    *,
    deny: set[str] | None = None,
    env: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """List ansible.builtin.* modules via ansible-doc when available."""
    deny = deny or set()
    mods = run_doc_list(env=env)
    if not mods:
        return []
    rows = []
    for fqcn in mods:
        if not fqcn.startswith("ansible.builtin."):
            continue
        if fqcn in deny:
            continue
        rows.append(
            {
                "fqcn": fqcn,
                "shortName": fqcn.split(".")[-1],
                "collection": "ansible.builtin",
                "description": fqcn.split(".")[-1],
                "downloadCount": 10**12,
                "collectionRank": 0,
                "source": "ansible-doc",
            }
        )
    return rows
