#!/usr/bin/env python3
"""Generate gallery.json + schemas from ansible-doc (when available).

Usage:
  python scripts/generate_catalog.py
  python scripts/generate_catalog.py --collections ansible.builtin,ansible.posix

Does not require network. Needs ansible-doc on PATH for full generation.
Without ansible-doc, exits 0 after validating existing catalog files.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog"


def load_allowlist() -> list[str]:
    import yaml

    data = yaml.safe_load((CATALOG / "collections-allowlist.yml").read_text(encoding="utf-8"))
    return list(data.get("collections") or [])


def run_doc_list() -> list[str] | None:
    try:
        out = subprocess.check_output(["ansible-doc", "-l", "-j"], text=True, timeout=120)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        return sorted(str(k) for k in data.keys())
    return None


def run_doc_json(fqcn: str) -> dict | None:
    try:
        out = subprocess.check_output(["ansible-doc", "-j", fqcn], text=True, timeout=60)
        data = json.loads(out)
        if isinstance(data, dict):
            # ansible-doc -j wraps under fqcn key sometimes
            if fqcn in data and isinstance(data[fqcn], dict):
                return data[fqcn]
            return data
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None
    return None


def normalize_schema(fqcn: str, doc: dict) -> dict:
    doc_root = doc.get("doc") if isinstance(doc.get("doc"), dict) else doc
    options_in = doc_root.get("options") if isinstance(doc_root, dict) else None
    options: list[dict] = []
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
            options.append(
                {
                    "name": name,
                    "displayName": str(name).replace("_", " ").title(),
                    "type": mapped,
                    "required": bool(meta.get("required")),
                    "default": meta.get("default"),
                    "description": str(meta.get("description") or "")[:500],
                    "choices": meta.get("choices") if isinstance(meta.get("choices"), list) else None,
                    "noLog": bool(meta.get("no_log")),
                    "suboptions": None,
                }
            )
    short = ""
    if isinstance(doc_root, dict):
        short = str(doc_root.get("short_description") or doc_root.get("description") or "")[:300]
    return {
        "fqcn": fqcn,
        "shortDescription": short,
        "docUrl": f"https://docs.ansible.com/ansible/latest/collections/{fqcn.replace('.', '/')}_module.html",
        "options": options,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--collections", default="")
    args = ap.parse_args()
    allow = [c.strip() for c in args.collections.split(",") if c.strip()] or load_allowlist()

    modules = run_doc_list()
    if modules is None:
        print("ansible-doc not available; leaving existing catalog intact.", file=sys.stderr)
        return 0

    selected = []
    for m in modules:
        coll = ".".join(m.split(".")[:2]) if m.count(".") >= 2 else ""
        if coll in allow:
            selected.append(m)

    gallery = []
    schemas_dir = CATALOG / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)

    for fqcn in selected:
        parts = fqcn.split(".")
        short = parts[-1] if parts else fqcn
        collection = ".".join(parts[:2]) if len(parts) >= 2 else ""
        doc = run_doc_json(fqcn)
        desc = ""
        if doc:
            schema = normalize_schema(fqcn, doc)
            desc = schema.get("shortDescription") or ""
            (schemas_dir / f"{fqcn}.json").write_text(
                json.dumps(schema, indent=2) + "\n", encoding="utf-8"
            )
        gallery.append(
            {
                "fqcn": fqcn,
                "shortName": short,
                "collection": collection,
                "description": desc or short,
            }
        )

    gallery.sort(key=lambda x: x["fqcn"])
    (CATALOG / "gallery.json").write_text(json.dumps(gallery, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(gallery)} gallery entries under {CATALOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
