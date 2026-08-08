"""Job queue + settings for the catalog factory."""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import (
    DEFAULT_SETTINGS,
    JOBS,
    NODES,
    QUEUE,
    SCANS,
    SETTINGS_PATH,
    WORKER_LOG,
    WORKER_PID,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_dirs() -> None:
    for p in (JOBS, SCANS, QUEUE, NODES):
        p.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict[str, Any]:
    ensure_dirs()
    s = dict(DEFAULT_SETTINGS)
    if SETTINGS_PATH.is_file():
        try:
            s.update(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    return s


def save_settings(settings: dict[str, Any]) -> None:
    ensure_dirs()
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def new_scan_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]


def save_scan(
    scan_id: str,
    *,
    collections: list[dict[str, Any]],
    modules: list[dict[str, Any]],
    meta: dict[str, Any] | None = None,
) -> Path:
    ensure_dirs()
    d = SCANS / scan_id
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": scan_id,
        "createdAt": _now(),
        "collectionCount": len(collections),
        "moduleCount": len(modules),
        **(meta or {}),
    }
    (d / "meta.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (d / "collections.json").write_text(
        json.dumps(collections, indent=2) + "\n", encoding="utf-8"
    )
    (d / "modules.json").write_text(json.dumps(modules, indent=2) + "\n", encoding="utf-8")
    (JOBS / "last_scan").write_text(scan_id + "\n", encoding="utf-8")
    return d


def last_scan_id() -> str | None:
    p = JOBS / "last_scan"
    if p.is_file():
        return p.read_text(encoding="utf-8").strip() or None
    scans = sorted(SCANS.iterdir(), reverse=True) if SCANS.is_dir() else []
    for s in scans:
        if s.is_dir() and (s / "modules.json").is_file():
            return s.name
    return None


def load_scan_modules(scan_id: str | None = None) -> list[dict[str, Any]]:
    sid = scan_id or last_scan_id()
    if not sid:
        return []
    path = SCANS / sid / "modules.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def load_scan_collections(scan_id: str | None = None) -> list[dict[str, Any]]:
    sid = scan_id or last_scan_id()
    if not sid:
        return []
    path = SCANS / sid / "collections.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def list_scans() -> list[dict[str, Any]]:
    if not SCANS.is_dir():
        return []
    out = []
    for d in sorted(SCANS.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        meta_p = d / "meta.json"
        meta: dict[str, Any] = {"id": d.name}
        if meta_p.is_file():
            try:
                meta.update(json.loads(meta_p.read_text(encoding="utf-8")))
            except Exception:
                pass
        out.append(meta)
    return out


def _job_path(job_id: str) -> Path:
    return QUEUE / f"{job_id}.json"


def _safe_job_name(fqcn: str) -> str:
    return fqcn.replace("/", "_").replace(" ", "_")


def enqueue(
    modules: list[dict[str, Any]],
    *,
    priority: int = 100,
    force: bool = False,
) -> int:
    """Enqueue module schema jobs. Returns count newly added."""
    ensure_dirs()
    existing_fqcns = {j.get("fqcn") for j in list_queue() if j.get("status") in ("pending", "running")}
    n = 0
    for i, m in enumerate(modules):
        fqcn = str(m.get("fqcn") or "").strip()
        if not fqcn:
            continue
        if not force and fqcn in existing_fqcns:
            continue
        job_id = f"{int(time.time() * 1000):x}-{_safe_job_name(fqcn)}"
        job = {
            "id": job_id,
            "fqcn": fqcn,
            "shortName": m.get("shortName") or fqcn.split(".")[-1],
            "collection": m.get("collection") or ".".join(fqcn.split(".")[:2]),
            "description": m.get("description") or "",
            "downloadCount": m.get("downloadCount") or 0,
            "source": m.get("source") or "galaxy",
            "status": "pending",
            "priority": int(priority) + i,
            "createdAt": _now(),
            "updatedAt": _now(),
            "attempts": 0,
            "error": "",
            "detail": "",
        }
        _job_path(job_id).write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
        existing_fqcns.add(fqcn)
        n += 1
    return n


def list_queue(*, status: str | None = None) -> list[dict[str, Any]]:
    ensure_dirs()
    rows: list[dict[str, Any]] = []
    for p in QUEUE.glob("*.json"):
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(j, dict):
            continue
        if status and status != "all" and j.get("status") != status:
            continue
        rows.append(j)
    rows.sort(key=lambda j: (int(j.get("priority") or 9999), str(j.get("createdAt") or "")))
    return rows


def queue_counts() -> dict[str, int]:
    c = {"all": 0, "pending": 0, "running": 0, "done": 0, "failed": 0, "skipped": 0}
    for j in list_queue():
        c["all"] += 1
        st = str(j.get("status") or "pending")
        c[st] = c.get(st, 0) + 1
    return c


def update_job(job_id: str, **fields: Any) -> dict[str, Any] | None:
    path = _job_path(job_id)
    if not path.is_file():
        return None
    try:
        job = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    job.update(fields)
    job["updatedAt"] = _now()
    path.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    return job


def claim_next_pending() -> dict[str, Any] | None:
    """Atomically-ish claim lowest priority pending job."""
    for j in list_queue(status="pending"):
        jid = str(j.get("id") or "")
        path = _job_path(jid)
        if not path.is_file():
            continue
        # simple claim via rename lock file
        lock = path.with_suffix(".claim")
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
        except FileExistsError:
            continue
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
            if job.get("status") != "pending":
                continue
            job["status"] = "running"
            job["attempts"] = int(job.get("attempts") or 0) + 1
            job["updatedAt"] = _now()
            job["pid"] = os.getpid()
            path.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
            return job
        finally:
            try:
                lock.unlink(missing_ok=True)
            except Exception:
                pass
    return None


def requeue_failed() -> int:
    n = 0
    for j in list_queue(status="failed"):
        if update_job(str(j["id"]), status="pending", error="", detail="requeued"):
            n += 1
    return n


def drop_done(keep_failed: bool = True) -> int:
    n = 0
    for j in list_queue():
        st = j.get("status")
        if st == "done" or (st == "failed" and not keep_failed) or st == "skipped":
            path = _job_path(str(j["id"]))
            try:
                path.unlink()
                n += 1
            except Exception:
                pass
    return n


def is_worker_alive() -> tuple[bool, str]:
    if not WORKER_PID.is_file():
        return False, ""
    try:
        pid = int(WORKER_PID.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)
        return True, str(pid)
    except Exception:
        return False, ""


def write_worker_pid() -> None:
    ensure_dirs()
    WORKER_PID.write_text(str(os.getpid()) + "\n", encoding="utf-8")


def clear_worker_pid() -> None:
    try:
        WORKER_PID.unlink(missing_ok=True)
    except Exception:
        pass


def append_log(msg: str) -> None:
    ensure_dirs()
    line = f"{_now()} {msg}\n"
    with open(WORKER_LOG, "a", encoding="utf-8") as f:
        f.write(line)


def tail_log(n: int = 200) -> list[str]:
    if not WORKER_LOG.is_file():
        return ["(no worker.log yet)"]
    try:
        lines = WORKER_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        return [f"(log read error: {e})"]
    return lines[-n:] if lines else ["(empty log)"]


def node_dir(fqcn: str) -> Path:
    ensure_dirs()
    d = NODES / _safe_job_name(fqcn)
    d.mkdir(parents=True, exist_ok=True)
    return d
