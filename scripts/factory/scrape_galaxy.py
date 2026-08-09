#!/usr/bin/env python3
"""Scrape top Ansible Galaxy collections → module inventory scan.

  python scripts/factory/scrape_galaxy.py
  python scripts/factory/scrape_galaxy.py --top 50 --enqueue
  python scripts/factory/scrape_galaxy.py --namespaces community,amazon --top 20
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.galaxy_client import client_from_settings, modules_from_hits  # noqa: E402
from lib.job_store import enqueue, load_settings, new_scan_id, save_scan  # noqa: E402
from lib.paths import DEFAULT_DENY  # noqa: E402
from lib.proxy_pool import ProxyPool  # noqa: E402
from lib.schema_gen import builtin_modules_from_doc  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape top Galaxy collections into a factory scan")
    ap.add_argument("--top", type=int, default=0, help="Top N collections (0=settings)")
    ap.add_argument("--page-size", type=int, default=0)
    ap.add_argument("--min-downloads", type=int, default=-1)
    ap.add_argument("--namespaces", default="", help="Comma filter e.g. community,amazon,ansible")
    ap.add_argument("--keywords", default="")
    ap.add_argument("--modules-per-collection", type=int, default=-1, help="0=all")
    ap.add_argument("--no-builtin", action="store_true")
    ap.add_argument("--enqueue", action="store_true", help="Enqueue all modules after scan")
    ap.add_argument("--json", action="store_true", help="Print scan summary JSON")
    ap.add_argument("--proxy", default="", help="Proxy URL e.g. socks5h://host:1080")
    ap.add_argument("--use-proxy", action="store_true", help="Force proxy on for this run")
    args = ap.parse_args()

    settings = load_settings()
    top = args.top or int(settings.get("topN") or 40)
    page = args.page_size or int(settings.get("galaxyPageSize") or 20)
    min_dl = (
        args.min_downloads
        if args.min_downloads >= 0
        else int(settings.get("minDownloadCount") or 0)
    )
    mpc = (
        args.modules_per_collection
        if args.modules_per_collection >= 0
        else int(settings.get("modulesPerCollection") or 0)
    )
    ns_raw = args.namespaces or str(settings.get("namespaceFilter") or "")
    namespaces = {x.strip() for x in ns_raw.split(",") if x.strip()} or None
    include_builtin = (not args.no_builtin) and bool(settings.get("includeBuiltin", True))

    if args.proxy:
        settings["proxy"] = args.proxy
        settings["useProxy"] = True
    if args.use_proxy:
        settings["useProxy"] = True
    pool = ProxyPool() if settings.get("useProxy") else None
    client = client_from_settings(settings, pool)

    def progress(msg: str) -> None:
        print(msg, file=sys.stderr)

    print(f"Fetching top {top} Galaxy collections…", file=sys.stderr)
    hits = client.search_top_collections(
        limit=top,
        page_size=page,
        min_download_count=min_dl,
        namespaces=namespaces,
        keywords=args.keywords,
        progress=progress,
    )

    collections = [
        {
            "namespace": h.namespace,
            "name": h.name,
            "fqcn": h.fqcn,
            "downloadCount": h.download_count,
            "description": h.description,
            "latestVersion": h.latest_version,
            "moduleCount": len(h.modules),
            "tags": h.tags,
        }
        for h in hits
    ]

    deny = set(DEFAULT_DENY) if settings.get("denyFreeform", True) else set()
    modules = modules_from_hits(hits, modules_per_collection=mpc, deny=deny)

    if include_builtin:
        builtins = builtin_modules_from_doc(deny=deny)
        if builtins:
            # prepend builtins not already present
            have = {m["fqcn"] for m in modules}
            extra = [b for b in builtins if b["fqcn"] not in have]
            modules = extra + modules
            print(f"Added {len(extra)} ansible.builtin modules from ansible-doc", file=sys.stderr)
        else:
            print(
                "ansible-doc not available — skipping ansible.builtin auto-list "
                "(Galaxy collections only)",
                file=sys.stderr,
            )

    scan_id = new_scan_id()
    save_scan(
        scan_id,
        collections=collections,
        modules=modules,
        meta={
            "topN": top,
            "namespaces": sorted(namespaces) if namespaces else [],
            "keywords": args.keywords,
            "includeBuiltin": include_builtin,
        },
    )
    print(
        f"Scan {scan_id}: {len(collections)} collections, {len(modules)} modules",
        file=sys.stderr,
    )
    for c in collections[:15]:
        print(
            f"  {c['downloadCount']:>12}  {c['fqcn']:<32}  mods={c['moduleCount']}",
            file=sys.stderr,
        )
    if len(collections) > 15:
        print(f"  … +{len(collections) - 15} more", file=sys.stderr)

    enq = 0
    if args.enqueue:
        enq = enqueue(modules)
        print(f"Enqueued {enq} schema jobs", file=sys.stderr)

    if args.json:
        print(
            json.dumps(
                {
                    "scanId": scan_id,
                    "collections": len(collections),
                    "modules": len(modules),
                    "enqueued": enq,
                },
                indent=2,
            )
        )
    else:
        print(scan_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
