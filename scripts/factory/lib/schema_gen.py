"""Generate slim module schemas (ansible-doc preferred, Galaxy stub fallback)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def run_doc_json(fqcn: str, *, timeout: float = 60) -> dict[str, Any] | None:
    try:
        out = subprocess.check_output(
            ["ansible-doc", "-j", fqcn],
            text=True,
            timeout=timeout,
            stderr=subprocess.DEVNULL,
        )
        data = json.loads(out)
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ):
        return None
    if isinstance(data, dict):
        if fqcn in data and isinstance(data[fqcn], dict):
            return data[fqcn]
        return data
    return None


def run_doc_list(*, timeout: float = 120) -> list[str] | None:
    try:
        out = subprocess.check_output(
            ["ansible-doc", "-l", "-j"],
            text=True,
            timeout=timeout,
            stderr=subprocess.DEVNULL,
        )
        data = json.loads(out)
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
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


def generate_schema(
    fqcn: str,
    *,
    description: str = "",
    prefer_ansible_doc: bool = True,
) -> tuple[dict[str, Any], str]:
    """Return (schema, method) where method is ansible-doc|stub."""
    if prefer_ansible_doc:
        doc = run_doc_json(fqcn)
        if doc:
            return normalize_schema(fqcn, doc), "ansible-doc"
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
) -> list[dict[str, Any]]:
    """List ansible.builtin.* modules via ansible-doc when available."""
    deny = deny or set()
    mods = run_doc_list()
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
                "downloadCount": 10**12,  # rank above galaxy
                "collectionRank": 0,
                "source": "ansible-doc",
            }
        )
    return rows
