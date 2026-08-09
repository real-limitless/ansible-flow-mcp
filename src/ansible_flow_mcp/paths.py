from __future__ import annotations

import os
from pathlib import Path

DEFAULT_HUB_DIR = Path("/var/lib/ansible-flow/hub")
DEFAULT_SPOKE_DIR = Path("/var/lib/ansible-flow/spoke")


def hub_dir(override: str | Path | None = None) -> Path:
    if override is not None:
        return Path(override).expanduser().resolve()
    env = os.environ.get("ANSIBLE_FLOW_HUB_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_HUB_DIR


def spoke_dir(override: str | Path | None = None) -> Path:
    if override is not None:
        return Path(override).expanduser().resolve()
    env = os.environ.get("ANSIBLE_FLOW_SPOKE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_SPOKE_DIR


def ensure_dir(path: Path, mode: int = 0o700) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, mode)
    except OSError:
        pass
    return path
