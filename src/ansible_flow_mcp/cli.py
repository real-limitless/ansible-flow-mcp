from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _out(data: Any) -> None:
    if isinstance(data, str):
        sys.stdout.write(data if data.endswith("\n") else data + "\n")
    else:
        sys.stdout.write(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n")


def _parse_ttl(text: str) -> int:
    raw = (text or "15m").strip().lower()
    if raw.endswith("s"):
        return int(raw[:-1])
    if raw.endswith("m"):
        return int(raw[:-1]) * 60
    if raw.endswith("h"):
        return int(raw[:-1]) * 3600
    return int(raw)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ansible-flow-mcp",
        description="Ansible Flow MCP — stdio server, hub controller, or spoke worker",
    )
    p.add_argument(
        "--hub-dir",
        default=None,
        help="Hub state directory (default: $ANSIBLE_FLOW_HUB_DIR or /var/lib/ansible-flow/hub)",
    )
    p.add_argument(
        "--spoke-dir",
        default=None,
        help="Spoke state directory (default: $ANSIBLE_FLOW_SPOKE_DIR or /var/lib/ansible-flow/spoke)",
    )
    sub = p.add_subparsers(dest="cmd")

    # hub
    hub = sub.add_parser("hub", help="Hub controller commands")
    hub_sub = hub.add_subparsers(dest="hub_cmd", required=True)

    h_init = hub_sub.add_parser("init", help="Initialize hub state (keys, inventory, CA)")
    h_init.add_argument("--name", default="hub-01")
    h_init.add_argument("--force", action="store_true")

    h_tok = hub_sub.add_parser("issue-token", help="Issue one-time join token")
    h_tok.add_argument("--name", required=True, help="Spoke node name")
    h_tok.add_argument("--ttl", default="15m", help="TTL e.g. 15m, 1h, 900")
    h_tok.add_argument(
        "--hub",
        default=None,
        help="Join SSH target for copy-paste command (default: mcp-join@$HOSTNAME or $ANSIBLE_FLOW_JOIN_HUB)",
    )
    h_tok.add_argument(
        "--public-addr",
        default=None,
        help="Address to put in spoke join command (default: --name)",
    )

    h_rev = hub_sub.add_parser("revoke", help="Revoke enrolled spoke")
    h_rev.add_argument("--name", required=True)

    hub_sub.add_parser("status", help="Show hub status / spokes + targets")
    hub_sub.add_parser("session", help="Run hub MCP stdio session")
    hub_sub.add_parser("tui", help="Operator TUI (servers, groups, OpenCode launch)")
    hub_sub.add_parser(
        "write-opencode-config",
        help="Write OpenCode MCP config pointing at hub session",
    )
    hub_sub.add_parser("accept-join", help="ForceCommand: accept spoke join JSON on stdin")

    h_call = hub_sub.add_parser("spoke-call", help="SSH ForceCommand MCP tool call on spoke")
    h_call.add_argument("--node", required=True)
    h_call.add_argument("--tool", default="list_collections")
    h_call.add_argument("--args", default="{}", help="JSON object of tool arguments")
    h_call.add_argument("--timeout", type=float, default=60.0)

    h_rt = hub_sub.add_parser(
        "register-target",
        help="Register Ansible-only target (WinRM/SSH/network; no spoke agent)",
    )
    h_rt.add_argument("--name", required=True)
    h_rt.add_argument("--host", required=True, dest="ansible_host", help="ansible_host")
    h_rt.add_argument(
        "--connection",
        default="ssh",
        dest="ansible_connection",
        help="ansible_connection (ssh, winrm, network_cli, ...)",
    )
    h_rt.add_argument("--port", type=int, default=None, dest="ansible_port")
    h_rt.add_argument("--user", default=None, dest="ansible_user")
    h_rt.add_argument(
        "--extra",
        default="{}",
        help="JSON object of allowlisted extra host vars (no passwords)",
    )

    h_ut = hub_sub.add_parser("update-target", help="Update registered Ansible target")
    h_ut.add_argument("--name", required=True)
    h_ut.add_argument("--host", default=None, dest="ansible_host")
    h_ut.add_argument("--connection", default=None, dest="ansible_connection")
    h_ut.add_argument("--port", type=int, default=None, dest="ansible_port")
    h_ut.add_argument("--user", default=None, dest="ansible_user")
    h_ut.add_argument("--extra", default="{}", help="JSON object of allowlisted extra host vars")

    h_rmt = hub_sub.add_parser("remove-target", help="Remove registered Ansible target")
    h_rmt.add_argument("--name", required=True)

    # spoke
    spoke = sub.add_parser("spoke", help="Spoke worker commands")
    spoke_sub = spoke.add_subparsers(dest="spoke_cmd", required=True)

    s_join = spoke_sub.add_parser("join", help="Enroll with hub using join token")
    s_join.add_argument("--token", required=True)
    s_join.add_argument("--hub", required=True, help="user@host[:port] for join SSH")
    s_join.add_argument("--public-addr", required=True, help="Address hub should use for this spoke")
    s_join.add_argument("--name", default=None, help="Node name (default: from token)")
    s_join.add_argument("--ssh-port", type=int, default=22, help="Spoke sshd port hub will dial")
    s_join.add_argument("--identity", default=None, help="SSH identity for join channel")
    s_join.add_argument(
        "--authorized-keys",
        default=None,
        help="Path to write hub client authorized_keys line",
    )

    spoke_sub.add_parser("session", help="ForceCommand MCP stdio (localhost only)")
    spoke_sub.add_parser("status", help="Show spoke enrollment status")

    return p


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)

    # No subcommand → legacy/dev stdio MCP
    if not argv or argv[0] not in {"hub", "spoke", "tui", "-h", "--help"}:
        if argv and argv[0] in {"-h", "--help"}:
            build_parser().print_help()
            return
        from ansible_flow_mcp.server import run_server

        run_server(role=None)
        return

    # top-level tui shortcut
    if argv[0] == "tui":
        rest = argv[1:]
        hub_path = None
        # allow --hub-dir before/after
        import os

        if "--hub-dir" in rest:
            i = rest.index("--hub-dir")
            if i + 1 < len(rest):
                hub_path = Path(rest[i + 1]).expanduser()
                os.environ["ANSIBLE_FLOW_HUB_DIR"] = str(hub_path)
        from ansible_flow_mcp.tui import run_tui

        run_tui(hub_root=hub_path)
        return

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.hub_dir:
        import os

        os.environ["ANSIBLE_FLOW_HUB_DIR"] = str(Path(args.hub_dir).expanduser())
    if args.spoke_dir:
        import os

        os.environ["ANSIBLE_FLOW_SPOKE_DIR"] = str(Path(args.spoke_dir).expanduser())

    if args.cmd == "hub":
        _hub_main(args)
        return
    if args.cmd == "spoke":
        _spoke_main(args)
        return
    parser.print_help()


def _hub_main(args: argparse.Namespace) -> None:
    from ansible_flow_mcp.hub.enroll import accept_join_stdio, hub_status, revoke_node
    from ansible_flow_mcp.hub.state import hub_init, load_hub_state
    from ansible_flow_mcp.hub.tokens import issue_token
    from ansible_flow_mcp.paths import hub_dir

    root = hub_dir()

    if args.hub_cmd == "init":
        st = hub_init(name=args.name, root=root, force=bool(args.force))
        _out(
            {
                "ok": True,
                "hub_id": st.hub_id,
                "name": st.name,
                "root": str(st.root),
                "inventory": str(st.inventory_path),
                "client_pub": st.client_pub_path.read_text(encoding="utf-8").strip(),
            }
        )
        return

    if args.hub_cmd == "issue-token":
        from ansible_flow_mcp.tui import build_spoke_join_command, default_join_hub

        st = load_hub_state(root)
        issued = issue_token(args.name, ttl_seconds=_parse_ttl(args.ttl), state=st)
        join_hub = (args.hub or "").strip() or default_join_hub()
        pub = (args.public_addr or "").strip() or args.name
        payload = issued.to_dict()
        payload["join_hub"] = join_hub
        payload["public_addr"] = pub
        payload["join_command"] = build_spoke_join_command(
            token=issued.token,
            hub=join_hub,
            name=args.name,
            public_addr=pub,
        )
        _out(payload)
        return

    if args.hub_cmd == "revoke":
        _out(revoke_node(args.name, root=root))
        return

    if args.hub_cmd == "status":
        _out(hub_status(root=root))
        return

    if args.hub_cmd == "tui":
        from ansible_flow_mcp.tui import run_tui

        run_tui(hub_root=root)
        return

    if args.hub_cmd == "write-opencode-config":
        from ansible_flow_mcp.tui import App, write_opencode_hub_config

        path = write_opencode_hub_config(App(hub_root=root, hub_ok=True))
        _out({"ok": True, "path": str(path)})
        return

    if args.hub_cmd == "session":
        import os

        os.environ["ANSIBLE_FLOW_ROLE"] = "hub"
        from ansible_flow_mcp.server import run_server

        run_server(role="hub")
        return

    if args.hub_cmd == "accept-join":
        code = accept_join_stdio()
        raise SystemExit(code)

    if args.hub_cmd == "spoke-call":
        from ansible_flow_mcp.ssh import spoke_call

        try:
            arguments = json.loads(args.args)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"invalid --args JSON: {exc}") from exc
        result = spoke_call(
            args.node,
            tool=args.tool,
            arguments=arguments,
            root=root,
            timeout=float(args.timeout),
        )
        _out(result.to_dict())
        if not result.ok:
            raise SystemExit(1)
        return

    if args.hub_cmd == "register-target":
        from ansible_flow_mcp.hub.enroll import register_target

        try:
            extra = json.loads(args.extra)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"invalid --extra JSON: {exc}") from exc
        if extra is not None and not isinstance(extra, dict):
            raise SystemExit("--extra must be a JSON object")
        _out(
            register_target(
                args.name,
                ansible_host=args.ansible_host,
                ansible_connection=args.ansible_connection,
                ansible_port=args.ansible_port,
                ansible_user=args.ansible_user,
                extra=extra or None,
                root=root,
            )
        )
        return

    if args.hub_cmd == "update-target":
        from ansible_flow_mcp.hub.enroll import update_target_node

        try:
            extra = json.loads(args.extra)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"invalid --extra JSON: {exc}") from exc
        if extra is not None and not isinstance(extra, dict):
            raise SystemExit("--extra must be a JSON object")
        _out(
            update_target_node(
                args.name,
                ansible_host=args.ansible_host,
                ansible_port=args.ansible_port,
                ansible_user=args.ansible_user,
                ansible_connection=args.ansible_connection,
                extra=extra or None,
                root=root,
            )
        )
        return

    if args.hub_cmd == "remove-target":
        from ansible_flow_mcp.hub.enroll import remove_target_node

        _out(remove_target_node(args.name, root=root))
        return

    raise SystemExit(f"unknown hub command: {args.hub_cmd}")


def _spoke_main(args: argparse.Namespace) -> None:
    from ansible_flow_mcp.paths import spoke_dir
    from ansible_flow_mcp.spoke.join import spoke_join, spoke_status

    root = spoke_dir()

    if args.spoke_cmd == "join":
        from pathlib import Path as P

        result = spoke_join(
            token=args.token,
            hub=args.hub,
            public_addr=args.public_addr,
            node_name=args.name,
            ssh_port=int(args.ssh_port),
            root=root,
            identity=P(args.identity) if args.identity else None,
            auth_keys_path=P(args.authorized_keys) if args.authorized_keys else None,
        )
        _out(result)
        return

    if args.spoke_cmd == "session":
        from ansible_flow_mcp.spoke.session import run_spoke_session

        run_spoke_session()
        return

    if args.spoke_cmd == "status":
        _out(spoke_status(root=root))
        return

    raise SystemExit(f"unknown spoke command: {args.spoke_cmd}")


if __name__ == "__main__":
    main()
