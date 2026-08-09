from __future__ import annotations

import os
import sys
from pathlib import Path

PROD_HUB_DIR = Path("/var/lib/ansible-flow/hub")
PROD_SPOKE_DIR = Path("/var/lib/ansible-flow/spoke")


def _xdg_data_home() -> Path:
    raw = os.environ.get("XDG_DATA_HOME")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".local" / "share"


def _user_state_dir(kind: str) -> Path:
    return _xdg_data_home() / "ansible-flow" / kind


def _can_use(path: Path) -> bool:
    """True if path is usable now or its nearest existing ancestor is writable."""
    try:
        if path.exists():
            return os.access(path, os.W_OK | os.X_OK)
        cur = path
        while not cur.exists():
            parent = cur.parent
            if parent == cur:
                return False
            cur = parent
        return os.access(cur, os.W_OK | os.X_OK)
    except OSError:
        return False


def default_hub_dir() -> Path:
    if _can_use(PROD_HUB_DIR):
        return PROD_HUB_DIR
    return _user_state_dir("hub")


def default_spoke_dir() -> Path:
    if _can_use(PROD_SPOKE_DIR):
        return PROD_SPOKE_DIR
    return _user_state_dir("spoke")


# Back-compat aliases (resolved at import for simple Path compares in docs/tests)
DEFAULT_HUB_DIR = PROD_HUB_DIR
DEFAULT_SPOKE_DIR = PROD_SPOKE_DIR


def hub_dir(override: str | Path | None = None) -> Path:
    if override is not None:
        return Path(override).expanduser().resolve()
    env = os.environ.get("ANSIBLE_FLOW_HUB_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return default_hub_dir().expanduser().resolve()


def spoke_dir(override: str | Path | None = None) -> Path:
    if override is not None:
        return Path(override).expanduser().resolve()
    env = os.environ.get("ANSIBLE_FLOW_SPOKE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return default_spoke_dir().expanduser().resolve()


def ensure_dir(path: Path, mode: int = 0o700) -> Path:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        hint = (
            f"Cannot create state directory {path}.\n"
            "Fix one of:\n"
            f"  • export ANSIBLE_FLOW_HUB_DIR=$HOME/.local/share/ansible-flow/hub\n"
            f"  • ansible-flow-mcp hub init --hub-dir ~/.local/share/ansible-flow/hub\n"
            f"  • sudo mkdir -p {path} && sudo chown \"$USER\" {path}\n"
        )
        print(hint, file=sys.stderr)
        raise PermissionError(hint) from exc
    try:
        os.chmod(path, mode)
    except OSError:
        pass
    return path
