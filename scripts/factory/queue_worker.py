#!/usr/bin/env python3
"""Drain factory queue: install collection if needed → ansible-doc schema → gallery.

  python scripts/factory/queue_worker.py
  python scripts/factory/queue_worker.py --once
  python scripts/factory/queue_worker.py --concurrency 2
"""
from __future__ import annotations

import argparse
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.catalog_io import (  # noqa: E402
    ensure_collection_allowlisted,
    upsert_gallery_entry,
)
from lib.install_collections import (  # noqa: E402
    ansible_env,
    ensure_collection_for_fqcn,
)
from lib.job_store import (  # noqa: E402
    append_log,
    claim_next_pending,
    clear_worker_pid,
    is_worker_alive,
    load_settings,
    node_dir,
    queue_counts,
    update_job,
    write_worker_pid,
)
from lib.paths import SCHEMAS  # noqa: E402
from lib.schema_gen import SchemaUnavailable, generate_schema, write_schema  # noqa: E402

_STOP = False


def _handle_sig(_s: int, _f: object) -> None:
    global _STOP
    _STOP = True
    append_log("signal — draining in-flight then stop")


def process_job(job: dict, settings: dict) -> None:
    jid = str(job["id"])
    fqcn = str(job["fqcn"])
    prefer = bool(settings.get("preferAnsibleDoc", True))
    auto_al = bool(settings.get("autoAllowlist", True))
    require_real = bool(settings.get("requireRealSchema", True))
    try:
        ok_inst, inst_msg = ensure_collection_for_fqcn(fqcn, settings)
        if not ok_inst and require_real:
            update_job(
                jid,
                status="failed",
                error=f"collection install: {inst_msg}"[:400],
                detail="install-failed",
            )
            append_log(f"FAIL {fqcn}: install {inst_msg}")
            return

        env = ansible_env(settings)
        schema, method = generate_schema(
            fqcn,
            description=str(job.get("description") or ""),
            prefer_ansible_doc=prefer,
            require_real=require_real,
            env=env,
        )
        if method == "stub" and require_real:
            raise SchemaUnavailable(f"refusing stub for {fqcn}")

        path = write_schema(schema, SCHEMAS)
        nd = node_dir(fqcn)
        (nd / "schema.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        (nd / "status.json").write_text(
            f'{{"fqcn": "{fqcn}", "method": "{method}", "status": "done"}}\n',
            encoding="utf-8",
        )
        desc = schema.get("shortDescription") or job.get("description") or fqcn
        upsert_gallery_entry(
            {
                "fqcn": fqcn,
                "shortName": job.get("shortName") or fqcn.split(".")[-1],
                "collection": job.get("collection") or ".".join(fqcn.split(".")[:2]),
                "description": desc,
                "downloadCount": job.get("downloadCount"),
                "source": method,
            }
        )
        coll = str(job.get("collection") or ".".join(fqcn.split(".")[:2]))
        if auto_al and coll:
            ensure_collection_allowlisted(coll)
        nopt = len(schema.get("options") or [])
        update_job(
            jid,
            status="done",
            detail=f"{method} options={nopt}",
            error="",
            method=method,
        )
        append_log(f"DONE {fqcn} via {method} opts={nopt}")
    except SchemaUnavailable as e:
        update_job(jid, status="failed", error=str(e)[:400], detail="no-real-schema")
        append_log(f"FAIL {fqcn}: {e}")
    except Exception as e:
        update_job(jid, status="failed", error=str(e)[:400], detail="exception")
        append_log(f"FAIL {fqcn}: {e}")


def run_batch(concurrency: int, settings: dict) -> int:
    jobs = []
    for _ in range(max(1, concurrency)):
        j = claim_next_pending()
        if not j:
            break
        jobs.append(j)
    if not jobs:
        return 0
    # Install is process-global locked; keep concurrency modest
    if concurrency <= 1 or len(jobs) == 1:
        for j in jobs:
            if _STOP:
                update_job(str(j["id"]), status="pending", detail="interrupted")
                continue
            process_job(j, settings)
        return len(jobs)
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = {ex.submit(process_job, j, settings): j for j in jobs}
        for fut in as_completed(futs):
            try:
                fut.result()
            except Exception as e:
                j = futs[fut]
                append_log(f"worker future error {j.get('fqcn')}: {e}")
    return len(jobs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="Process one batch then exit")
    ap.add_argument("--concurrency", type=int, default=0)
    ap.add_argument("--idle-exit", type=int, default=3, help="Empty polls before exit (0=forever)")
    ap.add_argument("--force", action="store_true", help="Start even if pidfile alive")
    args = ap.parse_args()

    alive, pid = is_worker_alive()
    if alive and not args.force:
        print(f"Worker already running pid={pid}", file=sys.stderr)
        return 1

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    settings = load_settings()
    conc = args.concurrency or int(settings.get("concurrency") or 2)
    write_worker_pid()
    append_log(
        f"worker start conc={conc} requireReal={settings.get('requireRealSchema', True)} "
        f"autoInstall={settings.get('autoInstallCollections', True)}"
    )
    print(f"Factory worker started conc={conc}", file=sys.stderr)

    idle = 0
    try:
        while not _STOP:
            settings = load_settings()
            conc = args.concurrency or int(settings.get("concurrency") or 2)
            n = run_batch(conc, settings)
            if n == 0:
                idle += 1
                c = queue_counts()
                append_log(f"idle poll pending={c.get('pending', 0)} done={c.get('done', 0)}")
                if args.once:
                    break
                if args.idle_exit and idle >= args.idle_exit:
                    append_log("idle-exit")
                    break
                time.sleep(1.0)
            else:
                idle = 0
                if args.once:
                    break
                time.sleep(0.05)
    finally:
        clear_worker_pid()
        append_log("worker stop")
        print("Worker stopped", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
