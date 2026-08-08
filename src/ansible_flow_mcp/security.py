from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

FQCN_RE = re.compile(r"^[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+$")


@dataclass
class SecurityPolicy:
    collections: set[str] = field(default_factory=set)
    deny_modules: set[str] = field(default_factory=set)
    fqcn_pattern: re.Pattern[str] = field(default=FQCN_RE)

    def assert_module_allowed(self, fqcn: str) -> str:
        fqcn = (fqcn or "").strip()
        if not self.fqcn_pattern.match(fqcn):
            raise ValueError(f"Invalid module FQCN: {fqcn!r}")
        if fqcn in self.deny_modules:
            raise ValueError(f"Module is denied by policy: {fqcn}")
        collection = ".".join(fqcn.split(".")[:2])
        if self.collections and collection not in self.collections:
            raise ValueError(
                f"Collection {collection!r} is not in the allowlist "
                f"({', '.join(sorted(self.collections))})"
            )
        return fqcn


def _default_catalog_dir() -> Path:
    env = os.environ.get("ANSIBLE_FLOW_CATALOG_DIR")
    if env:
        return Path(env).expanduser().resolve()
    # package-installed catalog
    pkg = Path(__file__).resolve().parent / "catalog"
    if pkg.is_dir():
        return pkg
    # repo layout: <root>/catalog
    repo = Path(__file__).resolve().parents[2] / "catalog"
    return repo


def load_policy(catalog_dir: Path | None = None) -> SecurityPolicy:
    root = catalog_dir or _default_catalog_dir()
    path = root / "collections-allowlist.yml"
    collections: set[str] = set()
    deny: set[str] = set()
    pattern = FQCN_RE

    if path.is_file():
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        collections = {str(c).strip() for c in data.get("collections") or [] if str(c).strip()}
        deny = {str(m).strip() for m in data.get("deny_modules") or [] if str(m).strip()}
        raw_pat = data.get("fqcn_pattern")
        if isinstance(raw_pat, str) and raw_pat.strip():
            pattern = re.compile(raw_pat.strip())

    env_cols = os.environ.get("ANSIBLE_FLOW_COLLECTIONS")
    if env_cols:
        collections = {c.strip() for c in env_cols.split(",") if c.strip()}

    return SecurityPolicy(collections=collections, deny_modules=deny, fqcn_pattern=pattern)


def redact_secrets(obj: Any, no_log_keys: set[str] | None = None) -> Any:
    """Shallow redaction for known secret-ish keys in nested dicts."""
    keys = no_log_keys or {
        "password",
        "passwd",
        "login_password",
        "api_key",
        "token",
        "secret",
        "ansible_password",
        "ansible_become_password",
    }
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if str(k).lower() in keys or str(k).lower().endswith("password"):
                out[k] = "********"
            else:
                out[k] = redact_secrets(v, keys)
        return out
    if isinstance(obj, list):
        return [redact_secrets(x, keys) for x in obj]
    return obj
