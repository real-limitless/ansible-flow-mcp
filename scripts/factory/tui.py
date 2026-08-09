#!/usr/bin/env python3
"""
Ansible Flow catalog factory TUI

Scrape top Galaxy collections → cherry-pick modules → queue schema jobs →
merge into catalog/gallery.json + schemas/.

  python scripts/factory/tui.py
"""
from __future__ import annotations

import curses
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.catalog_io import gallery_fqcns, repair_gallery, schema_exists  # noqa: E402
from lib.galaxy_client import client_from_settings, modules_from_hits  # noqa: E402
from lib.job_store import (  # noqa: E402
    append_log,
    drop_done,
    enqueue,
    is_worker_alive,
    last_scan_id,
    list_queue,
    list_scans,
    load_scan_collections,
    load_scan_modules,
    load_settings,
    new_scan_id,
    queue_counts,
    requeue_failed,
    save_scan,
    save_settings,
    tail_log,
    update_job,
)
from lib.paths import DEFAULT_DENY, DEFAULT_SETTINGS, JOBS, WORKER_LOG  # noqa: E402
from lib.proxy_pool import ProxyPool  # noqa: E402
from lib.schema_gen import builtin_modules_from_doc  # noqa: E402

MODES = ("scan", "list", "queue", "proxies", "settings", "log", "help")


@dataclass
class App:
    mode: str = "scan"
    message: str = ""
    # scan
    scan_running: bool = False
    scan_progress: str = ""
    active_scan_id: str | None = None
    collections: list[dict[str, Any]] = field(default_factory=list)
    coll_sel: int = 0
    coll_scroll: int = 0
    coll_selected: set[str] = field(default_factory=set)  # collection fqcn
    # list (modules)
    modules: list[dict[str, Any]] = field(default_factory=list)
    list_rows: list[dict[str, Any]] = field(default_factory=list)
    list_sel: int = 0
    list_scroll: int = 0
    list_selected: set[str] = field(default_factory=set)  # module fqcn
    list_filter: str = ""
    list_filter_mode: bool = False
    list_hide_known: bool = True
    # queue
    queue_rows: list[dict[str, Any]] = field(default_factory=list)
    queue_sel: int = 0
    queue_scroll: int = 0
    queue_filter: str = "all"
    # proxies
    proxy_pool: ProxyPool | None = None
    proxy_summary: dict[str, Any] = field(default_factory=dict)
    proxy_busy: bool = False
    proxy_input_mode: bool = False
    proxy_input_buf: str = ""
    # settings
    settings: dict[str, Any] = field(default_factory=dict)
    settings_keys: list[str] = field(default_factory=list)
    settings_sel: int = 0
    settings_edit: bool = False
    settings_buf: str = ""
    # log
    log_lines: list[str] = field(default_factory=list)
    log_scroll: int = 0
    log_follow: bool = True
    last_refresh: float = 0
    known_gallery: set[str] = field(default_factory=set)


def clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def safe_addstr(win: Any, y: int, x: int, text: str, attr: int = 0) -> None:
    try:
        h, w = win.getmaxyx()
        if y < 0 or y >= h or x >= w:
            return
        win.addstr(y, x, text[: max(0, w - x - 1)], attr)
    except curses.error:
        pass


def fmt_dl(n: int | float) -> str:
    n = int(n or 0)
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def rebuild_list(app: App) -> None:
    q = app.list_filter.lower().strip()
    rows = []
    for m in app.modules:
        fqcn = str(m.get("fqcn") or "")
        if app.list_hide_known and fqcn in app.known_gallery and schema_exists(fqcn):
            continue
        if q:
            hay = " ".join(
                str(m.get(k, ""))
                for k in ("fqcn", "shortName", "collection", "description")
            ).lower()
            if q not in hay:
                continue
        rows.append(m)
    app.list_rows = rows
    app.list_sel = clamp(app.list_sel, 0, max(0, len(rows) - 1))
    app.list_scroll = clamp(app.list_scroll, 0, max(0, len(rows) - 1))


def refresh_queue(app: App) -> None:
    st = None if app.queue_filter == "all" else app.queue_filter
    app.queue_rows = list_queue(status=st)
    app.queue_sel = clamp(app.queue_sel, 0, max(0, len(app.queue_rows) - 1))


def refresh_log(app: App) -> None:
    app.log_lines = tail_log(500)
    if app.log_follow:
        app.log_scroll = max(0, len(app.log_lines) - 1)


def load_last_scan_into_app(app: App) -> None:
    sid = last_scan_id()
    app.active_scan_id = sid
    app.collections = load_scan_collections(sid)
    app.modules = load_scan_modules(sid)
    app.coll_selected = {str(c.get("fqcn")) for c in app.collections if c.get("fqcn")}
    rebuild_list(app)


def start_scan(app: App) -> None:
    if app.scan_running:
        app.message = "Scan already running"
        return
    app.scan_running = True
    app.scan_progress = "starting…"
    px = "proxy" if app.settings.get("useProxy") else "direct"
    app.message = f"Galaxy scan started ({px})…"
    settings = dict(app.settings)
    pool = app.proxy_pool

    def run() -> None:
        try:
            client = client_from_settings(settings, pool)
            top = int(settings.get("topN") or 40)
            page = int(settings.get("galaxyPageSize") or 20)
            min_dl = int(settings.get("minDownloadCount") or 0)
            ns_raw = str(settings.get("namespaceFilter") or "")
            namespaces = {x.strip() for x in ns_raw.split(",") if x.strip()} or None
            mpc = int(settings.get("modulesPerCollection") or 0)

            def progress(msg: str) -> None:
                app.scan_progress = msg

            hits = client.search_top_collections(
                limit=top,
                page_size=page,
                min_download_count=min_dl,
                namespaces=namespaces,
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
            if settings.get("includeBuiltin", True):
                builtins = builtin_modules_from_doc(deny=deny)
                have = {m["fqcn"] for m in modules}
                modules = [b for b in builtins if b["fqcn"] not in have] + modules
            scan_id = new_scan_id()
            save_scan(
                scan_id,
                collections=collections,
                modules=modules,
                meta={"topN": top, "via": "tui"},
            )
            app.active_scan_id = scan_id
            app.collections = collections
            app.modules = modules
            app.coll_selected = {c["fqcn"] for c in collections}
            app.coll_sel = 0
            app.coll_scroll = 0
            app.list_selected = set()
            app.known_gallery = gallery_fqcns()
            rebuild_list(app)
            app.message = (
                f"Scan OK · {scan_id} · {len(collections)} collections · "
                f"{len(modules)} modules · Tab→LIST"
            )
            app.scan_progress = "done"
        except Exception as e:
            app.message = f"Scan failed: {e}"
            app.scan_progress = "error"
        finally:
            app.scan_running = False

    threading.Thread(target=run, daemon=True).start()


def start_worker(app: App) -> None:
    alive, pid = is_worker_alive()
    if alive:
        app.message = f"Worker already running pid={pid}"
        return
    JOBS.mkdir(parents=True, exist_ok=True)
    log = open(WORKER_LOG, "a", encoding="utf-8")
    conc = int(app.settings.get("concurrency") or 4)
    subprocess.Popen(
        [sys.executable, str(ROOT / "queue_worker.py"), "--concurrency", str(conc), "--idle-exit", "0"],
        cwd=str(REPO),
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    time.sleep(0.3)
    alive, pid = is_worker_alive()
    app.message = f"Worker started pid={pid or '…'} conc={conc}"
    append_log(f"TUI started worker pid={pid}")


def stop_worker(app: App) -> None:
    alive, pid = is_worker_alive()
    if not alive or not pid:
        app.message = "No worker running"
        return
    try:
        os.kill(int(pid), 15)
        app.message = f"Sent SIGTERM to worker {pid}"
    except Exception as e:
        app.message = f"Stop failed: {e}"


def enqueue_selected(app: App, *, all_visible: bool = False) -> None:
    if all_visible:
        mods = list(app.list_rows)
    else:
        mods = [m for m in app.list_rows if m.get("fqcn") in app.list_selected]
        if not mods and app.list_rows:
            # enqueue focused row
            mods = [app.list_rows[app.list_sel]]
    if not mods:
        app.message = "Nothing to enqueue"
        return
    n = enqueue(mods)
    app.message = f"Enqueued {n} jobs (skipped dupes)"
    refresh_queue(app)


def enqueue_selected_collections(app: App) -> None:
    """Enqueue modules belonging to selected collections."""
    if not app.coll_selected:
        app.message = "No collections selected — Space to toggle"
        return
    mods = [m for m in app.modules if m.get("collection") in app.coll_selected]
    if app.list_hide_known:
        mods = [
            m
            for m in mods
            if str(m.get("fqcn")) not in app.known_gallery or not schema_exists(str(m.get("fqcn")))
        ]
    n = enqueue(mods)
    app.message = f"Enqueued {n} from {len(app.coll_selected)} collections"
    refresh_queue(app)


def draw_header(stdscr: Any, app: App, h: int, w: int) -> None:
    alive, pid = is_worker_alive()
    c = queue_counts()
    rs = "RUN" if alive else "IDLE"
    title = (
        f" Ansible Flow Factory  ·  {rs} pid={pid or '-'}  ·  "
        f"q {c.get('pending', 0)}p/{c.get('running', 0)}r/{c.get('done', 0)}d/{c.get('failed', 0)}f  "
        f"scan={app.active_scan_id or '-'}  "
    )
    safe_addstr(stdscr, 0, 0, title.ljust(max(0, w - 1))[: w - 1], curses.A_BOLD | curses.color_pair(4))
    tabs = "  ".join(
        (f"[{m.upper()}]" if m == app.mode else m.upper()) for m in MODES if m != "help"
    )
    safe_addstr(stdscr, 1, 0, f" {tabs}   Tab=cycle  ?=help  q=quit"[: w - 1], curses.A_DIM)


def draw_footer(stdscr: Any, app: App, h: int, w: int) -> None:
    if app.mode == "scan":
        keys = "[Enter]scan top-N  [Space]toggle coll  [e]enqueue-sel-colls  [a]all-colls  [R]reload"
    elif app.mode == "list":
        keys = "[Space]pick  [a/A]all/clear  [e/E]enq sel/visible  [/]filter  [k]hide-known  [n]enq+start"
    elif app.mode == "queue":
        keys = "[S]tart worker  [X]stop  [r]requeue-fail  [d]drop-done  [1-5]filter  [R]refresh"
    elif app.mode == "proxies":
        keys = "[t]oggle useProxy  [R]efresh list  [H]ealth-check  [a]dd proxy  [s]ave settings"
    elif app.mode == "settings":
        keys = "[Enter]edit  [s]ave  [↑↓]field"
    elif app.mode == "log":
        keys = "[G]bottom  [g]top  [Space]follow  [R]refresh"
    else:
        keys = "[Esc/q] back"
    safe_addstr(stdscr, h - 2, 0, keys[: w - 1], curses.A_DIM)
    safe_addstr(stdscr, h - 1, 0, (app.message or "")[: w - 1].ljust(max(0, w - 1)))


def draw_scan(stdscr: Any, app: App, h: int, w: int) -> None:
    s = app.settings
    px = "proxy" if s.get("useProxy") else "direct"
    safe_addstr(
        stdscr,
        3,
        2,
        f"Top Galaxy collections  topN={s.get('topN')}  via={px}  ns={s.get('namespaceFilter') or '*'}  "
        f"{'SCANNING '+app.scan_progress if app.scan_running else 'Enter=scan'}"[: w - 3],
        curses.A_BOLD,
    )
    hdr = f"{'':1} {'#':>3}  {'DOWNLOADS':>10}  {'COLLECTION':<34}  {'MODS':>5}  DESCRIPTION"
    safe_addstr(stdscr, 4, 0, hdr[: w - 1], curses.A_DIM)
    view_h = max(1, h - 8)
    n = len(app.collections)
    if app.coll_sel < app.coll_scroll:
        app.coll_scroll = app.coll_sel
    if app.coll_sel >= app.coll_scroll + view_h:
        app.coll_scroll = app.coll_sel - view_h + 1
    for row in range(view_h):
        i = app.coll_scroll + row
        if i >= n:
            break
        c = app.collections[i]
        fq = str(c.get("fqcn") or "")
        mark = "*" if fq in app.coll_selected else " "
        cursor = "▶" if i == app.coll_sel else " "
        line = (
            f"{cursor}{mark}{i + 1:>3}  {fmt_dl(c.get('downloadCount', 0)):>10}  "
            f"{fq:<34}  {int(c.get('moduleCount') or 0):>5}  "
            f"{str(c.get('description') or '')[: max(10, w - 70)]}"
        )
        attr = curses.A_REVERSE if i == app.coll_sel else curses.A_NORMAL
        if fq in app.coll_selected:
            attr |= curses.color_pair(2)
        safe_addstr(stdscr, 5 + row, 0, line[: w - 1], attr)
    safe_addstr(
        stdscr,
        h - 3,
        2,
        f"{len(app.coll_selected)}/{n} collections selected · {len(app.modules)} modules in scan"[: w - 3],
    )


def draw_list(stdscr: Any, app: App, h: int, w: int) -> None:
    filt = f" filter={app.list_filter}_" if app.list_filter_mode else (
        f" filter={app.list_filter}" if app.list_filter else ""
    )
    hide = " hide-known=ON" if app.list_hide_known else " hide-known=OFF"
    safe_addstr(
        stdscr,
        3,
        2,
        f"Modules  showing={len(app.list_rows)}/{len(app.modules)}  picked={len(app.list_selected)}"
        f"{hide}{filt}"[: w - 3],
        curses.A_BOLD,
    )
    hdr = f"{'':1} {'FQCN':<48}  {'DL':>8}  {'IN CAT':>6}  DESCRIPTION"
    safe_addstr(stdscr, 4, 0, hdr[: w - 1], curses.A_DIM)
    view_h = max(1, h - 8)
    n = len(app.list_rows)
    if app.list_sel < app.list_scroll:
        app.list_scroll = app.list_sel
    if app.list_sel >= app.list_scroll + view_h:
        app.list_scroll = app.list_sel - view_h + 1
    for row in range(view_h):
        i = app.list_scroll + row
        if i >= n:
            break
        m = app.list_rows[i]
        fq = str(m.get("fqcn") or "")
        mark = "*" if fq in app.list_selected else " "
        cursor = "▶" if i == app.list_sel else " "
        known = "yes" if fq in app.known_gallery else "-"
        if schema_exists(fq):
            known = "schema"
        line = (
            f"{cursor}{mark} {fq:<46}  {fmt_dl(m.get('downloadCount', 0)):>8}  "
            f"{known:>6}  {str(m.get('description') or '')[: max(8, w - 72)]}"
        )
        attr = curses.A_REVERSE if i == app.list_sel else curses.A_NORMAL
        if fq in app.list_selected:
            attr |= curses.color_pair(2)
        elif known != "-":
            attr |= curses.color_pair(5)
        safe_addstr(stdscr, 5 + row, 0, line[: w - 1], attr)


def draw_queue(stdscr: Any, app: App, h: int, w: int) -> None:
    c = queue_counts()
    safe_addstr(
        stdscr,
        3,
        2,
        f"Queue filter={app.queue_filter}  all={c.get('all')} pend={c.get('pending')} "
        f"run={c.get('running')} done={c.get('done')} fail={c.get('failed')}"[: w - 3],
        curses.A_BOLD,
    )
    hdr = f"{'#':>4}  {'STATUS':<8}  {'FQCN':<44}  {'DETAIL'}"
    safe_addstr(stdscr, 4, 0, hdr[: w - 1], curses.A_DIM)
    view_h = max(1, h - 8)
    n = len(app.queue_rows)
    if app.queue_sel < app.queue_scroll:
        app.queue_scroll = app.queue_sel
    if app.queue_sel >= app.queue_scroll + view_h:
        app.queue_scroll = app.queue_sel - view_h + 1
    for row in range(view_h):
        i = app.queue_scroll + row
        if i >= n:
            break
        j = app.queue_rows[i]
        st = str(j.get("status") or "")
        cursor = "▶" if i == app.queue_sel else " "
        detail = str(j.get("error") or j.get("detail") or j.get("method") or "")[: max(8, w - 66)]
        line = f"{cursor}{i + 1:>3}  {st:<8}  {str(j.get('fqcn') or ''):<44}  {detail}"
        attr = curses.A_REVERSE if i == app.queue_sel else curses.A_NORMAL
        if st == "done":
            attr |= curses.color_pair(2)
        elif st == "failed":
            attr |= curses.color_pair(1)
        elif st == "running":
            attr |= curses.color_pair(3)
        safe_addstr(stdscr, 5 + row, 0, line[: w - 1], attr)


def draw_settings(stdscr: Any, app: App, h: int, w: int) -> None:
    safe_addstr(stdscr, 3, 2, "Factory settings → scripts/factory/.jobs/settings.json", curses.A_BOLD)
    keys = app.settings_keys
    view_h = max(1, h - 8)
    start = 0
    if app.settings_sel >= view_h:
        start = app.settings_sel - view_h + 1
    for row in range(view_h):
        idx = start + row
        if idx >= len(keys):
            break
        k = keys[idx]
        val = app.settings.get(k, DEFAULT_SETTINGS.get(k, ""))
        if app.settings_edit and idx == app.settings_sel:
            val_s = app.settings_buf + "_"
        else:
            val_s = json.dumps(val) if not isinstance(val, str) else val
        mark = "▶" if idx == app.settings_sel else " "
        attr = curses.A_REVERSE if idx == app.settings_sel else curses.A_NORMAL
        safe_addstr(stdscr, 5 + row, 2, f"{mark} {k}: {val_s}"[: w - 3], attr)


def draw_proxies(stdscr: Any, app: App, h: int, w: int) -> None:
    s = app.settings
    sum_ = app.proxy_summary or {}
    use = "ON" if s.get("useProxy") else "OFF"
    fixed = str(s.get("proxy") or "") or "(pool)"
    safe_addstr(stdscr, 3, 2, "Proxy — Galaxy HTTP via SOCKS5/HTTP", curses.A_BOLD)
    safe_addstr(
        stdscr,
        4,
        2,
        f"useProxy={use}  fixed={fixed}  listed={sum_.get('listed', 0)}  "
        f"alive={sum_.get('alive', 0)}  dead={sum_.get('dead', 0)}"[: w - 3],
    )
    safe_addstr(
        stdscr,
        5,
        2,
        f"listUrl={s.get('proxyListUrl') or ''}"[: w - 3],
        curses.A_DIM,
    )
    if app.proxy_pool:
        safe_addstr(
            stdscr,
            6,
            2,
            f"file={app.proxy_pool.list_path}"[: w - 3],
            curses.A_DIM,
        )
    lines = [
        "",
        "t  toggle useProxy (applies to Galaxy scan)",
        "R  refresh free SOCKS5 list (Databay / proxyListUrl)",
        "H  health-check sample against galaxy.ansible.com",
        "a  add fixed proxy (socks5h://host:port or host:port)",
        "c  clear fixed proxy (use rotating pool)",
        "s  save settings.json",
        "",
        "Also honors env: ALL_PROXY / HTTPS_PROXY / HTTP_PROXY",
        "Needs: pip install 'httpx[socks]'",
        "",
        "Jobs failed with 'Extra data' = corrupted gallery from parallel",
        "writes — fixed with lock. QUEUE→r requeues failed.",
    ]
    if app.proxy_input_mode:
        lines = [f"Add proxy: {app.proxy_input_buf}_", "(Enter confirm · Esc cancel)"] + lines
    if app.proxy_busy:
        lines = ["… busy …"] + lines
    for i, line in enumerate(lines):
        if 8 + i >= h - 2:
            break
        safe_addstr(stdscr, 8 + i, 2, line[: w - 3])


def draw_log(stdscr: Any, app: App, h: int, w: int) -> None:
    fl = "● LIVE" if app.log_follow else "⏸ PAUSED"
    safe_addstr(stdscr, 3, 2, f"{fl}  {WORKER_LOG}"[: w - 3], curses.A_BOLD)
    view_h = max(1, h - 6)
    n = len(app.log_lines)
    if app.log_follow:
        start = max(0, n - view_h)
        app.log_scroll = start
    else:
        start = clamp(app.log_scroll, 0, max(0, n - view_h))
        app.log_scroll = start
    for i in range(view_h):
        idx = start + i
        if idx >= n:
            break
        line = app.log_lines[idx]
        attr = curses.A_NORMAL
        if "FAIL" in line or "error" in line.lower():
            attr = curses.color_pair(1)
        elif "DONE" in line:
            attr = curses.color_pair(2)
        safe_addstr(stdscr, 4 + i, 0, line[: w - 1], attr)


def draw_help(stdscr: Any, app: App, h: int, w: int) -> None:
    lines = [
        "Ansible Flow Factory — Galaxy catalog scraper",
        "",
        "1. PROXIES — enable useProxy, refresh SOCKS5 list, health-check",
        "2. SETTINGS — topN, concurrency, proxy URL, namespaceFilter",
        "3. SCAN — Enter fetches top collections by download_count",
        "4. LIST — cherry-pick · e enqueue · n enqueue+start worker",
        "5. QUEUE — S start worker · r requeue failed",
        "",
        "Gallery writes are file-locked (fixes Extra data failures).",
        "Worker: ansible-doc when available; else stub schemas.",
        "",
        "pip install -r scripts/factory/requirements.txt",
        "python scripts/factory/tui.py",
    ]
    for i, line in enumerate(lines):
        if 3 + i >= h - 2:
            break
        safe_addstr(stdscr, 3 + i, 2, line[: w - 3])


def draw(stdscr: Any, app: App) -> None:
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    draw_header(stdscr, app, h, w)
    if app.mode == "scan":
        draw_scan(stdscr, app, h, w)
    elif app.mode == "list":
        draw_list(stdscr, app, h, w)
    elif app.mode == "queue":
        draw_queue(stdscr, app, h, w)
    elif app.mode == "proxies":
        draw_proxies(stdscr, app, h, w)
    elif app.mode == "settings":
        draw_settings(stdscr, app, h, w)
    elif app.mode == "log":
        draw_log(stdscr, app, h, w)
    elif app.mode == "help":
        draw_help(stdscr, app, h, w)
    draw_footer(stdscr, app, h, w)
    stdscr.refresh()


def refresh_proxy_summary(app: App) -> None:
    if app.proxy_pool:
        app.proxy_summary = app.proxy_pool.summary()


def proxy_refresh_bg(app: App) -> None:
    if app.proxy_busy or not app.proxy_pool:
        return
    app.proxy_busy = True
    app.message = "Refreshing proxy list…"
    settings = dict(app.settings)
    pool = app.proxy_pool

    def run() -> None:
        try:
            url = str(settings.get("proxyListUrl") or "")
            n = pool.refresh(source_url=url or None)
            app.proxy_summary = pool.summary()
            app.message = f"Proxy list refreshed · {n} entries"
        except Exception as e:
            app.message = f"Proxy refresh failed: {e}"
        finally:
            app.proxy_busy = False

    threading.Thread(target=run, daemon=True).start()


def proxy_health_bg(app: App) -> None:
    if app.proxy_busy or not app.proxy_pool:
        return
    app.proxy_busy = True
    app.message = "Health-checking proxies…"
    settings = dict(app.settings)
    pool = app.proxy_pool

    def run() -> None:
        try:
            r = pool.health_check(
                limit=int(settings.get("proxyProbeLimit") or 40),
                timeout=float(settings.get("proxyProbeTimeout") or 10),
            )
            app.proxy_summary = pool.summary()
            app.message = (
                f"Probe done · alive={r.get('probeAlive')} dead={r.get('probeDead')} "
                f"pool_alive={r.get('alive')}"
            )
        except Exception as e:
            app.message = f"Health-check failed: {e}"
        finally:
            app.proxy_busy = False

    threading.Thread(target=run, daemon=True).start()


def handle_settings_edit(app: App, ch: int) -> None:
    if ch in (27,):
        app.settings_edit = False
        return
    if ch in (10, 13):
        key = app.settings_keys[app.settings_sel]
        raw = app.settings_buf.strip()
        cur = app.settings.get(key)
        try:
            if isinstance(cur, bool):
                app.settings[key] = raw.lower() in ("1", "true", "yes", "on")
            elif isinstance(cur, int):
                app.settings[key] = int(raw)
            else:
                app.settings[key] = raw
        except ValueError:
            app.message = f"Invalid value for {key}"
            app.settings_edit = False
            return
        app.settings_edit = False
        app.message = f"Set {key} (s to save)"
        return
    if ch in (curses.KEY_BACKSPACE, 127, 8):
        app.settings_buf = app.settings_buf[:-1]
        return
    if 32 <= ch < 127:
        app.settings_buf += chr(ch)


def main_curses(stdscr: Any) -> None:
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_RED, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_YELLOW, -1)
    curses.init_pair(4, curses.COLOR_CYAN, -1)
    curses.init_pair(5, curses.COLOR_MAGENTA, -1)
    stdscr.nodelay(True)
    stdscr.timeout(200)
    stdscr.keypad(True)

    app = App()
    app.settings = load_settings()
    # merge new default keys
    for k, v in DEFAULT_SETTINGS.items():
        app.settings.setdefault(k, v)
    app.settings_keys = list(DEFAULT_SETTINGS.keys())
    app.proxy_pool = ProxyPool()
    refresh_proxy_summary(app)
    try:
        n = repair_gallery()
        append_log(f"gallery repair on start → {n} entries")
    except Exception as e:
        append_log(f"gallery repair skipped: {e}")
    app.known_gallery = gallery_fqcns()
    load_last_scan_into_app(app)
    refresh_queue(app)
    refresh_log(app)
    px = "proxyON" if app.settings.get("useProxy") else "direct"
    app.message = (
        f"Ready · {px} · last_scan={app.active_scan_id or 'none'} · "
        f"mods={len(app.modules)} · failed→QUEUE r · proxies Tab"
    )

    modes_cycle = [m for m in MODES if m != "help"]

    while True:
        now = time.time()
        if now - app.last_refresh > (0.5 if app.mode == "log" else 1.5):
            if app.mode == "queue":
                refresh_queue(app)
            if app.mode == "log":
                refresh_log(app)
            if app.mode == "proxies" and not app.proxy_busy:
                refresh_proxy_summary(app)
            app.last_refresh = now

        draw(stdscr, app)
        try:
            ch = stdscr.getch()
        except KeyboardInterrupt:
            break
        if ch == -1:
            continue

        if app.settings_edit:
            handle_settings_edit(app, ch)
            continue

        if app.proxy_input_mode:
            if ch in (27,):
                app.proxy_input_mode = False
                app.message = "Cancelled"
            elif ch in (10, 13):
                raw = app.proxy_input_buf.strip()
                app.proxy_input_mode = False
                if raw and app.proxy_pool:
                    try:
                        app.proxy_pool.add_proxy(raw)
                        # if looks like full URL, also set fixed proxy
                        if "://" in raw or raw.count(":") == 1:
                            parsed = app.proxy_pool.parse_proxy_lines(raw)
                            if parsed:
                                app.settings["proxy"] = parsed[0]
                                app.settings["useProxy"] = True
                        refresh_proxy_summary(app)
                        app.message = f"Added proxy · useProxy={app.settings.get('useProxy')}"
                    except Exception as e:
                        app.message = f"Add failed: {e}"
                else:
                    app.message = "Empty proxy"
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                app.proxy_input_buf = app.proxy_input_buf[:-1]
            elif 32 <= ch < 127:
                app.proxy_input_buf += chr(ch)
            continue

        if app.list_filter_mode:
            if ch in (27,):
                app.list_filter_mode = False
            elif ch in (10, 13):
                app.list_filter_mode = False
                rebuild_list(app)
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                app.list_filter = app.list_filter[:-1]
                rebuild_list(app)
            elif 32 <= ch < 127:
                app.list_filter += chr(ch)
                rebuild_list(app)
            continue

        if app.mode == "help":
            if ch in (27, ord("q"), ord("h"), ord("?")):
                app.mode = "scan"
            continue

        if ch == ord("q"):
            break
        if ch in (ord("?"),):
            app.mode = "help"
            continue
        if ch == 9:  # Tab
            i = modes_cycle.index(app.mode) if app.mode in modes_cycle else 0
            app.mode = modes_cycle[(i + 1) % len(modes_cycle)]
            if app.mode == "queue":
                refresh_queue(app)
            if app.mode == "log":
                refresh_log(app)
            if app.mode == "proxies":
                refresh_proxy_summary(app)
            continue
        if ch == curses.KEY_BTAB:
            i = modes_cycle.index(app.mode) if app.mode in modes_cycle else 0
            app.mode = modes_cycle[(i - 1) % len(modes_cycle)]
            continue

        # mode-specific
        if app.mode == "scan":
            if ch == curses.KEY_UP:
                app.coll_sel = max(0, app.coll_sel - 1)
            elif ch == curses.KEY_DOWN:
                app.coll_sel = min(max(0, len(app.collections) - 1), app.coll_sel + 1)
            elif ch == curses.KEY_PPAGE:
                app.coll_sel = max(0, app.coll_sel - 20)
            elif ch == curses.KEY_NPAGE:
                app.coll_sel = min(max(0, len(app.collections) - 1), app.coll_sel + 20)
            elif ch in (10, 13):
                start_scan(app)
            elif ch == ord(" "):
                if app.collections:
                    fq = str(app.collections[app.coll_sel].get("fqcn") or "")
                    if fq in app.coll_selected:
                        app.coll_selected.discard(fq)
                    else:
                        app.coll_selected.add(fq)
            elif ch == ord("a"):
                app.coll_selected = {
                    str(c.get("fqcn")) for c in app.collections if c.get("fqcn")
                }
                app.message = f"Selected all {len(app.coll_selected)} collections"
            elif ch == ord("A"):
                app.coll_selected.clear()
                app.message = "Cleared collection selection"
            elif ch == ord("e"):
                enqueue_selected_collections(app)
            elif ch == ord("R"):
                load_last_scan_into_app(app)
                app.known_gallery = gallery_fqcns()
                rebuild_list(app)
                scans = list_scans()
                app.message = f"Reloaded · {len(scans)} scans on disk"

        elif app.mode == "list":
            if ch == curses.KEY_UP:
                app.list_sel = max(0, app.list_sel - 1)
            elif ch == curses.KEY_DOWN:
                app.list_sel = min(max(0, len(app.list_rows) - 1), app.list_sel + 1)
            elif ch == curses.KEY_PPAGE:
                app.list_sel = max(0, app.list_sel - 20)
            elif ch == curses.KEY_NPAGE:
                app.list_sel = min(max(0, len(app.list_rows) - 1), app.list_sel + 20)
            elif ch == ord(" "):
                if app.list_rows:
                    fq = str(app.list_rows[app.list_sel].get("fqcn") or "")
                    if fq in app.list_selected:
                        app.list_selected.discard(fq)
                    else:
                        app.list_selected.add(fq)
            elif ch == ord("a"):
                app.list_selected = {str(m.get("fqcn")) for m in app.list_rows if m.get("fqcn")}
                app.message = f"Selected {len(app.list_selected)} modules"
            elif ch == ord("A"):
                app.list_selected.clear()
                app.message = "Cleared"
            elif ch == ord("e"):
                enqueue_selected(app, all_visible=False)
            elif ch == ord("E"):
                enqueue_selected(app, all_visible=True)
            elif ch == ord("n"):
                enqueue_selected(app, all_visible=bool(not app.list_selected))
                start_worker(app)
            elif ch == ord("/"):
                app.list_filter_mode = True
                app.message = "Filter modules…"
            elif ch == ord("k"):
                app.list_hide_known = not app.list_hide_known
                rebuild_list(app)
                app.message = f"hide-known={'ON' if app.list_hide_known else 'OFF'}"
            elif ch == ord("R"):
                app.known_gallery = gallery_fqcns()
                rebuild_list(app)
                app.message = "Gallery cache refreshed"

        elif app.mode == "queue":
            if ch == curses.KEY_UP:
                app.queue_sel = max(0, app.queue_sel - 1)
            elif ch == curses.KEY_DOWN:
                app.queue_sel = min(max(0, len(app.queue_rows) - 1), app.queue_sel + 1)
            elif ch == ord("S"):
                start_worker(app)
            elif ch == ord("X"):
                stop_worker(app)
            elif ch == ord("r"):
                n = requeue_failed()
                refresh_queue(app)
                app.message = f"Requeued {n} failed"
            elif ch == ord("d"):
                n = drop_done(keep_failed=True)
                refresh_queue(app)
                app.message = f"Dropped {n} done/skipped jobs"
            elif ch == ord("R"):
                refresh_queue(app)
                app.message = "Queue refreshed"
            elif ch == ord("1"):
                app.queue_filter = "all"
                refresh_queue(app)
            elif ch == ord("2"):
                app.queue_filter = "pending"
                refresh_queue(app)
            elif ch == ord("3"):
                app.queue_filter = "running"
                refresh_queue(app)
            elif ch == ord("4"):
                app.queue_filter = "done"
                refresh_queue(app)
            elif ch == ord("5"):
                app.queue_filter = "failed"
                refresh_queue(app)
            elif ch == ord("x") and app.queue_rows:
                j = app.queue_rows[app.queue_sel]
                update_job(str(j["id"]), status="skipped", detail="skipped by operator")
                refresh_queue(app)
                app.message = f"Skipped {j.get('fqcn')}"

        elif app.mode == "proxies":
            if ch == ord("t"):
                app.settings["useProxy"] = not bool(app.settings.get("useProxy"))
                app.message = f"useProxy={'ON' if app.settings.get('useProxy') else 'OFF'} (s to save)"
            elif ch == ord("R"):
                proxy_refresh_bg(app)
            elif ch == ord("H"):
                proxy_health_bg(app)
            elif ch == ord("a"):
                app.proxy_input_mode = True
                app.proxy_input_buf = str(app.settings.get("proxy") or "")
                app.message = "Type proxy URL…"
            elif ch == ord("c"):
                app.settings["proxy"] = ""
                app.message = "Cleared fixed proxy — pool will rotate (s to save)"
            elif ch == ord("s"):
                save_settings(app.settings)
                app.message = (
                    f"Saved useProxy={app.settings.get('useProxy')} "
                    f"proxy={app.settings.get('proxy') or '(pool)'}"
                )
            elif ch == ord(" "):
                # quick toggle
                app.settings["useProxy"] = not bool(app.settings.get("useProxy"))
                save_settings(app.settings)
                app.message = f"useProxy={'ON' if app.settings.get('useProxy') else 'OFF'} saved"

        elif app.mode == "settings":
            if ch == curses.KEY_UP:
                app.settings_sel = max(0, app.settings_sel - 1)
            elif ch == curses.KEY_DOWN:
                app.settings_sel = min(max(0, len(app.settings_keys) - 1), app.settings_sel + 1)
            elif ch in (10, 13):
                key = app.settings_keys[app.settings_sel]
                cur = app.settings.get(key, DEFAULT_SETTINGS.get(key, ""))
                if isinstance(cur, bool):
                    app.settings[key] = not cur
                    app.message = f"Toggled {key}={app.settings[key]} (s to save)"
                else:
                    app.settings_buf = json.dumps(cur) if not isinstance(cur, str) else str(cur)
                    app.settings_edit = True
            elif ch == ord("s"):
                save_settings(app.settings)
                app.message = "Settings saved"

        elif app.mode == "log":
            if ch in (ord("G"), curses.KEY_END):
                app.log_follow = True
                refresh_log(app)
            elif ch in (ord("g"), curses.KEY_HOME):
                app.log_follow = False
                app.log_scroll = 0
            elif ch == ord(" "):
                app.log_follow = not app.log_follow
            elif ch == curses.KEY_UP:
                app.log_follow = False
                app.log_scroll = max(0, app.log_scroll - 1)
            elif ch == curses.KEY_DOWN:
                app.log_scroll = min(max(0, len(app.log_lines) - 1), app.log_scroll + 1)
            elif ch == ord("R"):
                refresh_log(app)


def main() -> None:
    os.chdir(REPO)
    try:
        curses.wrapper(main_curses)
    except KeyboardInterrupt:
        pass
    alive, pid = is_worker_alive()
    if alive:
        print(f"Worker still running (pid={pid}). Stop from TUI QUEUE→X or kill {pid}")


if __name__ == "__main__":
    main()
