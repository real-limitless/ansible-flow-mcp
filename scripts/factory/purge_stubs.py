#!/usr/bin/env python3
"""Delete galaxy-stub schemas and requeue those FQCNs for real ansible-doc regen.

  python scripts/factory/purge_stubs.py
  python scripts/factory/purge_stubs.py --install
  python scripts/factory/purge_stubs.py --install --start-worker
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.install_collections import (  # noqa: E402
    collection_from_fqcn,
    install_many,
    list_installed,
)
from lib.job_store import (  # noqa: E402
    append_log,
    enqueue,
    is_worker_alive,
    list_queue,
    load_settings,
    queue_counts,
    update_job,
)
from lib.paths import SCHEMAS, WORKER_LOG  # noqa: E402


def find_stub_schemas() -> list[tuple[Path, str, dict]]:
    out: list[tuple[Path, str, dict]] = []
    if not SCHEMAS.is_dir():
        return out
    for p in sorted(SCHEMAS.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        src = str(data.get("source") or "")
        if src != "galaxy-stub":
            continue
        fqcn = str(data.get("fqcn") or p.stem)
        out.append((p, fqcn, data))
    return out


def reset_stub_done_jobs(stub_fqcns: set[str]) -> int:
    """Mark done jobs that were stubs (or match stub fqcns) back to pending."""
    n = 0
    for j in list_queue():
        fqcn = str(j.get("fqcn") or "")
        detail = str(j.get("detail") or "")
        method = str(j.get("method") or "")
        st = j.get("status")
        is_stub_job = (
            fqcn in stub_fqcns
            or "stub" in detail.lower()
            or method == "stub"
            or "galaxy-stub" in detail
        )
        if not is_stub_job:
            continue
        if st in ("done", "failed", "skipped", "running"):
            update_job(
                str(j["id"]),
                status="pending",
                error="",
                detail="requeued after stub purge",
                method="",
            )
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="Purge galaxy-stub schemas and requeue")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--install", action="store_true", help="Install missing collections first")
    ap.add_argument("--start-worker", action="store_true")
    ap.add_argument("--no-requeue", action="store_true")
    args = ap.parse_args()

    stubs = find_stub_schemas()
    fqcns = [fq for _, fq, _ in stubs]
    colls = sorted({collection_from_fqcn(f) for f in fqcns})
    print(f"Found {len(stubs)} galaxy-stub schemas across {len(colls)} collections", file=sys.stderr)

    if args.dry_run:
        for c in colls:
            n = sum(1 for f in fqcns if collection_from_fqcn(f) == c)
            print(f"  {n:5}  {c}", file=sys.stderr)
        print("dry-run — no changes", file=sys.stderr)
        return 0

    deleted = 0
    for path, fqcn, data in stubs:
        try:
            path.unlink()
            deleted += 1
        except Exception as e:
            print(f"unlink fail {path.name}: {e}", file=sys.stderr)
    print(f"Deleted {deleted} stub schema files", file=sys.stderr)
    append_log(f"purge_stubs deleted={deleted}")

    reset_n = reset_stub_done_jobs(set(fqcns))
    print(f"Reset {reset_n} queue jobs → pending", file=sys.stderr)

    enq = 0
    if not args.no_requeue and fqcns:
        mods = []
        for path, fqcn, data in stubs:
            mods.append(
                {
                    "fqcn": fqcn,
                    "shortName": data.get("shortName") or fqcn.split(".")[-1],
                    "collection": data.get("collection") or collection_from_fqcn(fqcn),
                    "description": data.get("shortDescription") or data.get("description") or "",
                    "source": "purge-requeue",
                }
            )
        # enqueue may skip existing pending — force via update already done;
        # still enqueue missing
        existing = {j.get("fqcn") for j in list_queue() if j.get("status") == "pending"}
        missing = [m for m in mods if m["fqcn"] not in existing]
        enq = enqueue(missing, force=True) if missing else 0
        print(f"Enqueued {enq} missing jobs (pending already covered rest)", file=sys.stderr)

    if args.install:
        settings = load_settings()
        need = [c for c in colls if c != "ansible.builtin"]
        installed = list_installed(settings, force=True)
        todo = [c for c in need if c not in installed]
        print(f"Installing {len(todo)} collections (skip {len(need) - len(todo)} already present)…", file=sys.stderr)

        def progress(msg: str) -> None:
            print(msg, file=sys.stderr)

        result = install_many(todo, settings, progress=progress)
        print(
            f"Install done ok={len(result['ok'])} fail={len(result['failed'])} "
            f"skipped={len(result['skipped'])} path={result['path']}",
            file=sys.stderr,
        )
        for f in result["failed"][:20]:
            print(f"  FAIL {f['collection']}: {f['error'][:120]}", file=sys.stderr)

    print("Queue:", queue_counts(), file=sys.stderr)

    if args.start_worker:
        alive, pid = is_worker_alive()
        if alive:
            print(f"Worker already running pid={pid}", file=sys.stderr)
        else:
            settings = load_settings()
            conc = int(settings.get("concurrency") or 2)
            log = open(WORKER_LOG, "a", encoding="utf-8")
            subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / "queue_worker.py"),
                    "--concurrency",
                    str(conc),
                    "--idle-exit",
                    "0",
                ],
                cwd=str(REPO),
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env={**os.environ},
            )
            time.sleep(0.4)
            alive, pid = is_worker_alive()
            print(f"Worker started pid={pid or '…'}", file=sys.stderr)
            append_log(f"purge_stubs started worker pid={pid}")

    print(
        json.dumps(
            {
                "deleted": deleted,
                "resetJobs": reset_n,
                "enqueued": enq,
                "collections": len(colls),
                "queue": queue_counts(),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
