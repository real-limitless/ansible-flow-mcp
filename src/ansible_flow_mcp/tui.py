"""Hub operator TUI — servers/groups CRUD + launch OpenCode with hub MCP.

  ansible-flow-mcp tui
  ansible-flow-mcp hub tui
"""
from __future__ import annotations

import curses
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ansible_flow_mcp.paths import hub_dir


MODES = ("servers", "groups", "hub", "help")


@dataclass
class App:
    mode: str = "servers"
    message: str = ""
    hub_root: Path | None = None
    hub_ok: bool = False
    hub_meta: dict[str, Any] = field(default_factory=dict)
    nodes: list[dict[str, Any]] = field(default_factory=list)
    groups: list[dict[str, Any]] = field(default_factory=list)
    sel: int = 0
    scroll: int = 0
    filter: str = ""
    filter_mode: bool = False
    modal: str | None = None  # invite|edit|group_new|group_members|confirm|token
    modal_buf: str = ""
    modal_field: int = 0
    modal_fields: list[str] = field(default_factory=list)
    modal_values: dict[str, str] = field(default_factory=dict)
    last_token: str = ""
    confirm_action: str = ""
    confirm_target: str = ""


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


def refresh_data(app: App) -> None:
    root = app.hub_root or hub_dir()
    app.hub_root = root
    if not (root / "hub_id").is_file():
        app.hub_ok = False
        app.hub_meta = {"root": str(root), "initialized": False}
        app.nodes = []
        app.groups = []
        return
    try:
        from ansible_flow_mcp.hub.enroll import hub_status

        st = hub_status(root=root)
        app.hub_ok = True
        app.hub_meta = st
        app.nodes = list(st.get("nodes") or [])
        app.groups = list(st.get("groups") or [])
    except Exception as exc:  # noqa: BLE001
        app.hub_ok = False
        app.message = f"load error: {exc}"
        app.nodes = []
        app.groups = []


def filtered_nodes(app: App) -> list[dict[str, Any]]:
    q = app.filter.lower().strip()
    if not q:
        return list(app.nodes)
    out = []
    for n in app.nodes:
        hay = " ".join(
            str(n.get(k, ""))
            for k in ("name", "ansible_host", "ansible_user", "groups")
        ).lower()
        if q in hay:
            out.append(n)
    return out


def filtered_groups(app: App) -> list[dict[str, Any]]:
    q = app.filter.lower().strip()
    if not q:
        return list(app.groups)
    return [g for g in app.groups if q in str(g.get("name", "")).lower()]


def ensure_sel(app: App, n: int) -> None:
    app.sel = clamp(app.sel, 0, max(0, n - 1))
    app.scroll = clamp(app.scroll, 0, max(0, n - 1))


def do_init(app: App, name: str = "hub-01") -> None:
    from ansible_flow_mcp.hub.state import hub_init

    root = app.hub_root or hub_dir()
    hub_init(name=name, root=root)
    app.message = f"hub initialized at {root}"
    refresh_data(app)


def do_invite(app: App, name: str, ttl: str = "15m") -> None:
    from ansible_flow_mcp.cli import _parse_ttl
    from ansible_flow_mcp.hub.tokens import issue_token

    issued = issue_token(name, ttl_seconds=_parse_ttl(ttl), root=app.hub_root)
    app.last_token = issued.token
    app.modal = "token"
    app.message = f"token issued for {name} (shown once)"
    refresh_data(app)


def do_revoke(app: App, name: str) -> None:
    from ansible_flow_mcp.hub.enroll import revoke_node

    revoke_node(name, root=app.hub_root)
    app.message = f"revoked {name}"
    refresh_data(app)


def do_update_node(app: App, name: str, host: str, port: str, user: str) -> None:
    from ansible_flow_mcp.hub.enroll import update_node

    kwargs: dict[str, Any] = {}
    if host.strip():
        kwargs["ansible_host"] = host.strip()
    if port.strip():
        kwargs["ansible_port"] = int(port.strip())
    if user.strip():
        kwargs["ansible_user"] = user.strip()
    update_node(name, root=app.hub_root, **kwargs)
    app.message = f"updated {name}"
    refresh_data(app)


def do_create_group(app: App, name: str) -> None:
    from ansible_flow_mcp.hub.enroll import create_group_op

    create_group_op(name, root=app.hub_root)
    app.message = f"group {name} created"
    refresh_data(app)


def do_delete_group(app: App, name: str) -> None:
    from ansible_flow_mcp.hub.enroll import delete_group_op

    delete_group_op(name, root=app.hub_root)
    app.message = f"group {name} deleted"
    refresh_data(app)


def do_set_members(app: App, name: str, hosts_csv: str) -> None:
    from ansible_flow_mcp.hub.enroll import set_group_members_op

    hosts = [h.strip() for h in hosts_csv.split(",") if h.strip()]
    set_group_members_op(name, hosts, root=app.hub_root)
    app.message = f"group {name} members set ({len(hosts)})"
    refresh_data(app)


def write_opencode_hub_config(app: App) -> Path:
    root = app.hub_root or hub_dir()
    bin_path = shutil.which("ansible-flow-mcp") or sys.argv[0]
    cfg = {
        "$schema": "https://opencode.ai/config.json",
        "mcp": {
            "ansible-flow-hub": {
                "type": "local",
                "command": [bin_path, "hub", "session"],
                "enabled": True,
                "environment": {
                    "ANSIBLE_FLOW_HUB_DIR": str(root),
                    "ANSIBLE_FLOW_ROLE": "hub",
                },
            }
        },
    }
    out = root / "opencode-hub.jsonc"
    # jsonc-compatible pure JSON
    out.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    # also project example copy under temp for OPENCODE_CONFIG
    return out


def launch_opencode(app: App) -> None:
    if not app.hub_ok:
        app.message = "init hub first"
        return
    oc = shutil.which("opencode")
    if not oc:
        app.message = "opencode not found on PATH"
        return
    cfg = write_opencode_hub_config(app)
    env = os.environ.copy()
    env["ANSIBLE_FLOW_HUB_DIR"] = str(app.hub_root)
    env["ANSIBLE_FLOW_ROLE"] = "hub"
    # Prefer project-local config if OpenCode honors OPENCODE_CONFIG
    env["OPENCODE_CONFIG"] = str(cfg)

    term = os.environ.get("ANSIBLE_FLOW_TUI_TERMINAL") or os.environ.get("TERMINAL")
    launched_ext = False
    if term and shutil.which(term.split()[0]):
        try:
            subprocess.Popen(
                [*term.split(), "-e", oc],
                env=env,
                cwd=str(app.hub_root),
                start_new_session=True,
            )
            launched_ext = True
            app.message = f"OpenCode launched in {term} (config {cfg})"
        except OSError:
            launched_ext = False

    if not launched_ext:
        # In-place: caller restores curses after return
        app.message = f"starting OpenCode (config {cfg})…"
        app.modal = "opencode_run"
        app.modal_buf = str(cfg)


def draw_header(stdscr: Any, app: App) -> None:
    h, w = stdscr.getmaxyx()
    title = " ansible-flow-mcp hub TUI "
    tabs = "  ".join(
        (f"[{m.upper()}]" if m == app.mode else m) for m in MODES
    )
    safe_addstr(stdscr, 0, 0, title.ljust(w), curses.A_REVERSE)
    safe_addstr(stdscr, 1, 0, tabs[: w - 1])
    status = f"hub={'ok' if app.hub_ok else 'missing'}  dir={app.hub_root}  / filter  A=AI  q=quit"
    safe_addstr(stdscr, 2, 0, status[: w - 1], curses.A_DIM)


def draw_footer(stdscr: Any, app: App) -> None:
    h, w = stdscr.getmaxyx()
    if app.filter_mode:
        msg = f"filter: {app.filter}_"
    else:
        msg = app.message or "keys: j/k select  i invite  e edit  d revoke  g new-group  m members  x del-group  A OpenCode  r refresh  ?"
    safe_addstr(stdscr, h - 1, 0, msg[: w - 1], curses.A_REVERSE)


def draw_servers(stdscr: Any, app: App) -> None:
    h, w = stdscr.getmaxyx()
    rows = filtered_nodes(app)
    ensure_sel(app, len(rows))
    safe_addstr(stdscr, 4, 0, f"{'NAME':16} {'HOST':22} {'PORT':6} {'USER':12} GROUPS")
    top = 5
    view = h - top - 2
    if app.sel < app.scroll:
        app.scroll = app.sel
    if app.sel >= app.scroll + view:
        app.scroll = app.sel - view + 1
    for i, n in enumerate(rows[app.scroll : app.scroll + view]):
        y = top + i
        idx = app.scroll + i
        line = (
            f"{str(n.get('name') or ''):16} "
            f"{str(n.get('ansible_host') or ''):22} "
            f"{str(n.get('ansible_port') or 22):6} "
            f"{str(n.get('ansible_user') or ''):12} "
            f"{','.join(n.get('groups') or [])}"
        )
        attr = curses.A_REVERSE if idx == app.sel else 0
        safe_addstr(stdscr, y, 0, line[: w - 1], attr)
    if not rows:
        safe_addstr(stdscr, top, 0, "(no enrolled spokes — press i to invite)", curses.A_DIM)


def draw_groups(stdscr: Any, app: App) -> None:
    h, w = stdscr.getmaxyx()
    rows = filtered_groups(app)
    ensure_sel(app, len(rows))
    safe_addstr(stdscr, 4, 0, f"{'GROUP':20} MEMBERS")
    top = 5
    view = h - top - 2
    if app.sel < app.scroll:
        app.scroll = app.sel
    if app.sel >= app.scroll + view:
        app.scroll = app.sel - view + 1
    for i, g in enumerate(rows[app.scroll : app.scroll + view]):
        y = top + i
        idx = app.scroll + i
        hosts = ",".join(g.get("hosts") or [])
        line = f"{str(g.get('name') or ''):20} {hosts}"
        attr = curses.A_REVERSE if idx == app.sel else 0
        safe_addstr(stdscr, y, 0, line[: w - 1], attr)
    if not rows:
        safe_addstr(stdscr, top, 0, "(no custom groups — press g to create)", curses.A_DIM)


def draw_hub(stdscr: Any, app: App) -> None:
    m = app.hub_meta
    lines = [
        f"initialized: {app.hub_ok}",
        f"name:       {m.get('name')}",
        f"hub_id:     {m.get('hub_id')}",
        f"root:       {m.get('root') or app.hub_root}",
        f"inventory:  {m.get('inventory')}",
        f"spokes:     {len(m.get('spokes') or [])}",
        f"groups:     {len(m.get('groups') or [])}",
        "",
        "n = init hub (if missing)",
        "A = write OpenCode config + launch hub MCP session",
    ]
    for i, line in enumerate(lines):
        safe_addstr(stdscr, 4 + i, 0, line)


def draw_help(stdscr: Any, app: App) -> None:
    lines = [
        "Servers: list enrolled spokes from hub inventory",
        "  i  invite (issue join token)",
        "  e  edit host/port/user",
        "  d  revoke selected spoke",
        "  p  ping via spoke_call list_collections",
        "Groups: Ansible targeting groups (enrolled members only)",
        "  g  create group   m  set members (csv)   x  delete group",
        "Global:",
        "  1/2/3/? tabs   / filter   r refresh   A OpenCode+hub MCP   q quit",
        "Create server = invite token; spoke must join. Groups cannot add unenrolled hosts.",
    ]
    for i, line in enumerate(lines):
        safe_addstr(stdscr, 4 + i, 0, line)


def draw_modal(stdscr: Any, app: App) -> None:
    h, w = stdscr.getmaxyx()
    box_h, box_w = 10, min(72, w - 4)
    y0, x0 = max(2, (h - box_h) // 2), max(1, (w - box_w) // 2)
    title = app.modal or ""
    for i in range(box_h):
        safe_addstr(stdscr, y0 + i, x0, " " * box_w, curses.A_REVERSE)
    safe_addstr(stdscr, y0, x0, f" {title} ".ljust(box_w), curses.A_REVERSE | curses.A_BOLD)

    if app.modal == "token":
        safe_addstr(stdscr, y0 + 2, x0 + 2, "Join token (copy now — shown once):", curses.A_REVERSE)
        tok = app.last_token
        for i in range(0, len(tok), box_w - 4):
            safe_addstr(stdscr, y0 + 3 + i // (box_w - 4), x0 + 2, tok[i : i + box_w - 4], curses.A_REVERSE)
        safe_addstr(stdscr, y0 + box_h - 2, x0 + 2, "Enter/Esc to close", curses.A_REVERSE)
        return

    if app.modal == "confirm":
        safe_addstr(
            stdscr,
            y0 + 3,
            x0 + 2,
            f"Confirm {app.confirm_action} {app.confirm_target}? [y/N]",
            curses.A_REVERSE,
        )
        return

    # field editor
    labels = app.modal_fields or ["value"]
    for i, lab in enumerate(labels):
        val = app.modal_values.get(lab, "")
        mark = ">" if i == app.modal_field else " "
        safe_addstr(stdscr, y0 + 2 + i, x0 + 2, f"{mark} {lab}: {val}", curses.A_REVERSE)
    safe_addstr(stdscr, y0 + box_h - 2, x0 + 2, "Tab fields  Enter submit  Esc cancel", curses.A_REVERSE)


def open_modal(app: App, kind: str, **kwargs: Any) -> None:
    app.modal = kind
    app.modal_field = 0
    app.modal_values = {}
    if kind == "invite":
        app.modal_fields = ["name", "ttl"]
        app.modal_values = {"name": "", "ttl": "15m"}
    elif kind == "edit":
        n = kwargs.get("node") or {}
        app.modal_fields = ["name", "ansible_host", "ansible_port", "ansible_user"]
        app.modal_values = {
            "name": str(n.get("name") or ""),
            "ansible_host": str(n.get("ansible_host") or ""),
            "ansible_port": str(n.get("ansible_port") or "22"),
            "ansible_user": str(n.get("ansible_user") or "mcp-spoke"),
        }
    elif kind == "group_new":
        app.modal_fields = ["name"]
        app.modal_values = {"name": ""}
    elif kind == "group_members":
        g = kwargs.get("group") or {}
        app.modal_fields = ["name", "hosts"]
        app.modal_values = {
            "name": str(g.get("name") or ""),
            "hosts": ",".join(g.get("hosts") or []),
        }
    elif kind == "confirm":
        app.confirm_action = str(kwargs.get("action") or "")
        app.confirm_target = str(kwargs.get("target") or "")
    elif kind == "init":
        app.modal_fields = ["name"]
        app.modal_values = {"name": "hub-01"}


def submit_modal(app: App) -> None:
    kind = app.modal
    app.modal = None
    try:
        if kind == "invite":
            do_invite(app, app.modal_values.get("name", ""), app.modal_values.get("ttl", "15m"))
            return
        if kind == "edit":
            name = app.modal_values.get("name", "")
            do_update_node(
                app,
                name,
                app.modal_values.get("ansible_host", ""),
                app.modal_values.get("ansible_port", ""),
                app.modal_values.get("ansible_user", ""),
            )
            return
        if kind == "group_new":
            do_create_group(app, app.modal_values.get("name", ""))
            return
        if kind == "group_members":
            do_set_members(
                app,
                app.modal_values.get("name", ""),
                app.modal_values.get("hosts", ""),
            )
            return
        if kind == "init":
            do_init(app, app.modal_values.get("name", "hub-01"))
            return
        if kind == "confirm":
            return
        if kind == "token":
            app.last_token = ""
            return
    except Exception as exc:  # noqa: BLE001
        app.message = f"error: {exc}"


def handle_confirm_yes(app: App) -> None:
    try:
        if app.confirm_action == "revoke":
            do_revoke(app, app.confirm_target)
        elif app.confirm_action == "delete_group":
            do_delete_group(app, app.confirm_target)
    except Exception as exc:  # noqa: BLE001
        app.message = f"error: {exc}"
    app.modal = None


def do_ping(app: App, name: str) -> None:
    from ansible_flow_mcp.ssh import spoke_call

    try:
        r = spoke_call(name, tool="list_collections", root=app.hub_root, timeout=30)
        app.message = f"ping {name}: {'ok' if r.ok else 'fail'} rc={r.exit_code}"
    except Exception as exc:  # noqa: BLE001
        app.message = f"ping error: {exc}"


def selected_node(app: App) -> dict[str, Any] | None:
    rows = filtered_nodes(app)
    if not rows:
        return None
    return rows[clamp(app.sel, 0, len(rows) - 1)]


def selected_group(app: App) -> dict[str, Any] | None:
    rows = filtered_groups(app)
    if not rows:
        return None
    return rows[clamp(app.sel, 0, len(rows) - 1)]


def handle_key(stdscr: Any, app: App, key: int) -> bool:
    """Return False to quit."""
    if app.modal == "opencode_run":
        return True

    if app.modal == "token":
        if key in (27, 10, 13, ord("q")):
            app.modal = None
            app.last_token = ""
        return True

    if app.modal == "confirm":
        if key in (ord("y"), ord("Y")):
            handle_confirm_yes(app)
        elif key in (27, ord("n"), ord("N"), 10, 13):
            app.modal = None
            app.message = "cancelled"
        return True

    if app.modal and app.modal not in {"token", "confirm", "opencode_run"}:
        labels = app.modal_fields
        cur = labels[app.modal_field] if labels else "value"
        if key == 27:
            app.modal = None
            return True
        if key == 9:  # tab
            app.modal_field = (app.modal_field + 1) % max(1, len(labels))
            return True
        if key in (10, 13):
            submit_modal(app)
            return True
        if key in (curses.KEY_BACKSPACE, 127, 8):
            app.modal_values[cur] = app.modal_values.get(cur, "")[:-1]
            return True
        if 32 <= key < 127:
            app.modal_values[cur] = app.modal_values.get(cur, "") + chr(key)
            return True
        return True

    if app.filter_mode:
        if key == 27:
            app.filter_mode = False
            return True
        if key in (10, 13):
            app.filter_mode = False
            return True
        if key in (curses.KEY_BACKSPACE, 127, 8):
            app.filter = app.filter[:-1]
            return True
        if 32 <= key < 127:
            app.filter += chr(key)
            return True
        return True

    if key in (ord("q"), 27):
        return False
    if key == ord("r"):
        refresh_data(app)
        app.message = "refreshed"
        return True
    if key == ord("/"):
        app.filter_mode = True
        return True
    if key == ord("1"):
        app.mode = "servers"
        app.sel = 0
        return True
    if key == ord("2"):
        app.mode = "groups"
        app.sel = 0
        return True
    if key == ord("3"):
        app.mode = "hub"
        return True
    if key in (ord("?"), ord("4")):
        app.mode = "help"
        return True
    if key == ord("A"):
        launch_opencode(app)
        return True

    if key in (curses.KEY_UP, ord("k")):
        app.sel = max(0, app.sel - 1)
        return True
    if key in (curses.KEY_DOWN, ord("j")):
        app.sel += 1
        return True

    if app.mode == "hub" and key == ord("n"):
        if app.hub_ok:
            app.message = "hub already initialized"
        else:
            open_modal(app, "init")
        return True

    if app.mode == "servers":
        if key == ord("i"):
            if not app.hub_ok:
                app.message = "init hub first (Hub tab, n)"
            else:
                open_modal(app, "invite")
            return True
        if key == ord("e"):
            n = selected_node(app)
            if not n:
                app.message = "no spoke selected"
            else:
                open_modal(app, "edit", node=n)
            return True
        if key == ord("d"):
            n = selected_node(app)
            if not n:
                app.message = "no spoke selected"
            else:
                open_modal(app, "confirm", action="revoke", target=str(n.get("name")))
            return True
        if key == ord("p"):
            n = selected_node(app)
            if n:
                do_ping(app, str(n.get("name")))
            return True

    if app.mode == "groups":
        if key == ord("g"):
            open_modal(app, "group_new")
            return True
        if key == ord("m"):
            g = selected_group(app)
            if not g:
                app.message = "no group selected"
            else:
                open_modal(app, "group_members", group=g)
            return True
        if key == ord("x"):
            g = selected_group(app)
            if not g:
                app.message = "no group selected"
            else:
                open_modal(app, "confirm", action="delete_group", target=str(g.get("name")))
            return True

    return True


def run_curses(stdscr: Any, app: App) -> None:
    curses.curs_set(0)
    stdscr.nodelay(False)
    stdscr.keypad(True)
    refresh_data(app)
    if not app.hub_ok:
        app.message = "hub not initialized — open Hub tab (3) and press n"

    while True:
        if app.modal == "opencode_run":
            cfg = app.modal_buf
            app.modal = None
            curses.endwin()
            env = os.environ.copy()
            env["OPENCODE_CONFIG"] = cfg
            env["ANSIBLE_FLOW_HUB_DIR"] = str(app.hub_root or "")
            env["ANSIBLE_FLOW_ROLE"] = "hub"
            try:
                subprocess.call([shutil.which("opencode") or "opencode"], env=env, cwd=str(app.hub_root or Path.cwd()))
            except OSError as exc:
                app.message = f"opencode failed: {exc}"
            else:
                app.message = "returned from OpenCode"
            stdscr.clear()
            curses.curs_set(0)
            continue

        stdscr.erase()
        draw_header(stdscr, app)
        if app.mode == "servers":
            draw_servers(stdscr, app)
        elif app.mode == "groups":
            draw_groups(stdscr, app)
        elif app.mode == "hub":
            draw_hub(stdscr, app)
        else:
            draw_help(stdscr, app)
        if app.modal:
            draw_modal(stdscr, app)
        draw_footer(stdscr, app)
        stdscr.refresh()
        key = stdscr.getch()
        if not handle_key(stdscr, app, key):
            break


def run_tui(*, hub_root: Path | None = None) -> None:
    if hub_root is not None:
        os.environ["ANSIBLE_FLOW_HUB_DIR"] = str(hub_root)
    app = App(hub_root=hub_root or hub_dir())
    try:
        curses.wrapper(lambda s: run_curses(s, app))
    except curses.error as exc:
        raise SystemExit(f"TUI failed (need a real terminal): {exc}") from exc


def main() -> None:
    run_tui()


if __name__ == "__main__":
    main()
