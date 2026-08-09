"""Install Ansible collections into factory .jobs/collections for ansible-doc.

Installs are fully serialized (thread + process lock). Concurrent galaxy
installs into the same path race and leave broken dirs (Errno 39 Directory
not empty / missing MANIFEST.json).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .job_store import append_log, load_settings
from .paths import JOBS

_LOCK = threading.RLock()
_INSTALLED_CACHE: set[str] | None = None
# soft fail: collection -> monotonic time when failure recorded (retry after cooldown)
_FAILED_AT: dict[str, float] = {}
_FAIL_COOLDOWN_SEC = 120.0
_INSTALL_LOCKFILE = JOBS / "collections.install.lock"


def collections_path(settings: dict[str, Any] | None = None) -> Path:
    s = settings if settings is not None else load_settings()
    raw = str(s.get("collectionsPath") or "").strip()
    if raw:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = (JOBS / p).resolve() if not p.parts[0] == ".." else p.resolve()
        return p
    return JOBS / "collections"


def ansible_env(settings: dict[str, Any] | None = None) -> dict[str, str]:
    """Env for ansible-doc / ansible-galaxy with factory collections path + proxy."""
    s = settings if settings is not None else load_settings()
    env = dict(os.environ)
    cpath = collections_path(s)
    cpath.mkdir(parents=True, exist_ok=True)
    existing = env.get("ANSIBLE_COLLECTIONS_PATH") or env.get("COLLECTIONS_PATHS") or ""
    parts = [str(cpath)]
    if existing:
        parts.append(existing)
    user = Path.home() / ".ansible" / "collections"
    if user.is_dir():
        parts.append(str(user))
    joined = os.pathsep.join(parts)
    env["ANSIBLE_COLLECTIONS_PATH"] = joined
    env["COLLECTIONS_PATHS"] = joined

    if s.get("useProxy"):
        proxy = str(s.get("proxy") or "").strip()
        if proxy:
            env.setdefault("HTTP_PROXY", proxy)
            env.setdefault("HTTPS_PROXY", proxy)
            env.setdefault("ALL_PROXY", proxy)
            env.setdefault("http_proxy", proxy)
            env.setdefault("https_proxy", proxy)
            env.setdefault("all_proxy", proxy)
    return env


def collection_from_fqcn(fqcn: str) -> str:
    parts = fqcn.split(".")
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return fqcn


def skip_set(settings: dict[str, Any] | None = None) -> set[str]:
    s = settings if settings is not None else load_settings()
    raw = s.get("skipCollections") or []
    if isinstance(raw, str):
        return {x.strip() for x in raw.split(",") if x.strip()}
    return {str(x).strip() for x in raw if str(x).strip()}


def collection_dir(collection: str, settings: dict[str, Any] | None = None) -> Path:
    ns, _, name = collection.partition(".")
    return collections_path(settings) / "ansible_collections" / ns / name


def is_collection_ok(collection: str, settings: dict[str, Any] | None = None) -> bool:
    if collection == "ansible.builtin":
        return True
    d = collection_dir(collection, settings)
    return d.is_dir() and (
        (d / "MANIFEST.json").is_file() or (d / "galaxy.yml").is_file()
    )


def remove_broken_collection(collection: str, settings: dict[str, Any] | None = None) -> bool:
    """Remove incomplete install dir (no MANIFEST). Returns True if removed."""
    d = collection_dir(collection, settings)
    if not d.exists():
        return False
    if is_collection_ok(collection, settings):
        return False
    try:
        shutil.rmtree(d, ignore_errors=True)
        # parent ns dir if empty
        ns = d.parent
        try:
            if ns.is_dir() and not any(ns.iterdir()):
                ns.rmdir()
        except Exception:
            pass
        append_log(f"removed broken collection dir {d}")
        return True
    except Exception as e:
        append_log(f"failed to remove broken {d}: {e}")
        return False


def _process_install_lock(timeout: float = 900.0):
    """Cross-process exclusive lock around galaxy install."""
    class _Ctx:
        def __enter__(self_inner):
            _INSTALL_LOCKFILE.parent.mkdir(parents=True, exist_ok=True)
            deadline = time.time() + timeout
            self_inner.fd = None
            while True:
                try:
                    self_inner.fd = os.open(
                        str(_INSTALL_LOCKFILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY
                    )
                    os.write(self_inner.fd, f"{os.getpid()}\n".encode())
                    return self_inner
                except FileExistsError:
                    try:
                        age = time.time() - _INSTALL_LOCKFILE.stat().st_mtime
                        if age > timeout:
                            _INSTALL_LOCKFILE.unlink(missing_ok=True)
                            continue
                    except Exception:
                        pass
                    if time.time() >= deadline:
                        raise TimeoutError("collections install lock timeout")
                    time.sleep(0.25)

        def __exit__(self_inner, *exc):
            if getattr(self_inner, "fd", None) is not None:
                try:
                    os.close(self_inner.fd)
                except Exception:
                    pass
            try:
                _INSTALL_LOCKFILE.unlink(missing_ok=True)
            except Exception:
                pass

    return _Ctx()


def list_installed(settings: dict[str, Any] | None = None, *, force: bool = False) -> set[str]:
    global _INSTALLED_CACHE
    with _LOCK:
        if _INSTALLED_CACHE is not None and not force:
            return set(_INSTALLED_CACHE)
        found: set[str] = set()
        # filesystem is authoritative for our factory path
        cpath = collections_path(settings) / "ansible_collections"
        if cpath.is_dir():
            for ns in cpath.iterdir():
                if not ns.is_dir() or ns.name.startswith("."):
                    continue
                for name in ns.iterdir():
                    if not name.is_dir():
                        continue
                    col = f"{ns.name}.{name.name}"
                    if (name / "MANIFEST.json").is_file() or (name / "galaxy.yml").is_file():
                        found.add(col)
        user = Path.home() / ".ansible" / "collections" / "ansible_collections"
        if user.is_dir():
            for ns in user.iterdir():
                if not ns.is_dir():
                    continue
                for name in ns.iterdir():
                    if name.is_dir() and (
                        (name / "MANIFEST.json").is_file() or (name / "galaxy.yml").is_file()
                    ):
                        found.add(f"{ns.name}.{name.name}")
        found.add("ansible.builtin")
        _INSTALLED_CACHE = found
        return set(found)


def _mark_failed(collection: str) -> None:
    _FAILED_AT[collection] = time.monotonic()


def _clear_failed(collection: str) -> None:
    _FAILED_AT.pop(collection, None)


def _recently_failed(collection: str) -> bool:
    t = _FAILED_AT.get(collection)
    if t is None:
        return False
    if time.monotonic() - t < _FAIL_COOLDOWN_SEC:
        return True
    _FAILED_AT.pop(collection, None)
    return False


def install_collection(
    collection: str,
    settings: dict[str, Any] | None = None,
    *,
    log: Callable[[str], None] | None = None,
    force: bool = False,
) -> tuple[bool, str]:
    """Install one collection. Fully serialized. Returns (ok, message)."""
    s = settings if settings is not None else load_settings()
    collection = collection.strip()
    if not collection or collection == "ansible.builtin":
        return True, "builtin"
    if collection in skip_set(s):
        return False, f"skipped by skipCollections: {collection}"

    # fast path without process lock
    with _LOCK:
        if not force and is_collection_ok(collection, s):
            global _INSTALLED_CACHE
            if _INSTALLED_CACHE is not None:
                _INSTALLED_CACHE.add(collection)
            return True, "already installed"
        if not force and _recently_failed(collection):
            return False, f"recently failed (cooldown): {collection}"

    with _LOCK:
        with _process_install_lock():
            # re-check under lock
            if not force and is_collection_ok(collection, s):
                if _INSTALLED_CACHE is not None:
                    _INSTALLED_CACHE.add(collection)
                _clear_failed(collection)
                return True, "already installed"

            # wipe broken / force reinstall target
            d = collection_dir(collection, s)
            if d.exists() and (force or not is_collection_ok(collection, s)):
                shutil.rmtree(d, ignore_errors=True)
                append_log(f"cleared collection dir before install: {collection}")

            env = ansible_env(s)
            cpath = collections_path(s)
            cpath.mkdir(parents=True, exist_ok=True)
            cmd = [
                "ansible-galaxy",
                "collection",
                "install",
                collection,
                "-p",
                str(cpath),
                "--force",
            ]
            msg = f"install {collection} → {cpath}"
            if log:
                log(msg)
            append_log(msg)

            last_err = ""
            for attempt in range(1, 3):
                try:
                    proc = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=float(s.get("installTimeoutSec") or 600),
                        env=env,
                    )
                    out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
                    if proc.returncode != 0:
                        last_err = out[-500:] if out else f"rc={proc.returncode}"
                        # clean partial
                        if d.exists() and not is_collection_ok(collection, s):
                            shutil.rmtree(d, ignore_errors=True)
                        append_log(f"INSTALL FAIL attempt={attempt} {collection}: {last_err[:200]}")
                        time.sleep(1.5 * attempt)
                        continue
                    if not is_collection_ok(collection, s):
                        last_err = "install reported ok but MANIFEST.json missing"
                        if d.exists():
                            shutil.rmtree(d, ignore_errors=True)
                        append_log(f"INSTALL incomplete {collection}")
                        continue
                    if _INSTALLED_CACHE is not None:
                        _INSTALLED_CACHE.add(collection)
                    else:
                        list_installed(s, force=True)
                    _clear_failed(collection)
                    append_log(f"INSTALL OK {collection}")
                    return True, "installed"
                except subprocess.TimeoutExpired:
                    last_err = "timeout"
                    append_log(f"INSTALL TIMEOUT {collection}")
                    if d.exists() and not is_collection_ok(collection, s):
                        shutil.rmtree(d, ignore_errors=True)
                except FileNotFoundError:
                    return False, "ansible-galaxy not on PATH"
                except Exception as e:
                    last_err = str(e)[:300]
                    append_log(f"INSTALL EXC {collection}: {last_err}")

            _mark_failed(collection)
            return False, last_err or "install failed"


def ensure_collection_for_fqcn(
    fqcn: str,
    settings: dict[str, Any] | None = None,
    *,
    log: Callable[[str], None] | None = None,
) -> tuple[bool, str]:
    s = settings if settings is not None else load_settings()
    coll = collection_from_fqcn(fqcn)
    if not s.get("autoInstallCollections", True):
        if is_collection_ok(coll, s) or coll == "ansible.builtin":
            return True, "present"
        return False, f"not installed (autoInstallCollections=false): {coll}"
    return install_collection(coll, s, log=log)


def install_many(
    collections: list[str],
    settings: dict[str, Any] | None = None,
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    s = settings if settings is not None else load_settings()
    uniq = sorted({c for c in collections if c and c != "ansible.builtin"})
    skip = skip_set(s)
    ok, fail, skipped = [], [], []
    for i, c in enumerate(uniq, 1):
        if c in skip:
            skipped.append(c)
            if progress:
                progress(f"skip {c} ({i}/{len(uniq)})")
            continue
        if progress:
            progress(f"install {c} ({i}/{len(uniq)})")
        good, msg = install_collection(c, s, force=True)
        if good:
            ok.append(c)
        else:
            fail.append({"collection": c, "error": msg})
    return {
        "ok": ok,
        "failed": fail,
        "skipped": skipped,
        "path": str(collections_path(s)),
    }


def clear_fail_cache() -> None:
    _FAILED_AT.clear()
