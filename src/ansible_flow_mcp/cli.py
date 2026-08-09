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

    h_rev = hub_sub.add_parser("revoke", help="Revoke enrolled spoke")
    h_rev.add_argument("--name", required=True)

    hub_sub.add_parser("status", help="Show hub status / enrolled spokes")
    hub_sub.add_parser("session", help="Run hub MCP stdio session")
    hub_sub.add_parser("accept-join", help="ForceCommand: accept spoke join JSON on stdin")

    h_call = hub_sub.add_parser("spoke-call", help="SSH ForceCommand MCP tool call on spoke")
    h_call.add_argument("--node", required=True)
    h_call.add_argument("--tool", default="list_collections")
    h_call.add_argument("--args", default="{}", help="JSON object of tool arguments")
    h_call.add_argument("--timeout", type=float, default=60.0)

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
    if not argv or argv[0] not in {"hub", "spoke", "-h", "--help"}:
        if argv and argv[0] in {"-h", "--help"}:
            build_parser().print_help()
            return
        from ansible_flow_mcp.server import run_server

        run_server(role=None)
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
        st = load_hub_state(root)
        issued = issue_token(args.name, ttl_seconds=_parse_ttl(args.ttl), state=st)
        _out(issued.to_dict())
        return

    if args.hub_cmd == "revoke":
        _out(revoke_node(args.name, root=root))
        return

    if args.hub_cmd == "status":
        _out(hub_status(root=root))
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
