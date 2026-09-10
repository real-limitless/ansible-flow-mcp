"""Hub-local operator web console (login + TUI-equivalent ops)."""

from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

from ansible_flow_mcp.paths import hub_dir
from ansible_flow_mcp.web.auth import (
    clear_session_cookie,
    origin_ok,
    parse_credentials,
    read_session,
    set_session_cookie,
)
from ansible_flow_mcp.web.store import OperatorStore

STATIC = Path(__file__).resolve().parent / "static"
COOKIE_CSRF_HEADER = "x-csrf-token"


def create_app(hub_root: Path | None = None) -> Starlette:
    root = Path(hub_root or hub_dir()).expanduser().resolve()
    store = OperatorStore(root)

    def _json_error(message: str, status: int) -> JSONResponse:
        return JSONResponse({"error": message}, status_code=status)

    def _operator(request: Request):
        token = read_session(request)
        sess = store.auth_session(token) if token else None
        return sess

    async def require_user(request: Request):
        sess = _operator(request)
        if not sess:
            return None, _json_error("unauthorized", 401)
        operator, csrf = sess
        method = request.method.upper()
        if method not in {"GET", "HEAD", "OPTIONS"}:
            if not origin_ok(request):
                return None, _json_error("forbidden origin", 403)
            got = request.headers.get(COOKIE_CSRF_HEADER) or ""
            if not csrf or got != csrf:
                return None, _json_error("invalid csrf", 403)
        return operator, None

    async def body_json(request: Request) -> dict:
        try:
            data = await request.json()
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    async def auth_status(request: Request) -> JSONResponse:
        sess = _operator(request)
        return JSONResponse(
            {
                "setupRequired": store.count() == 0,
                "authenticated": sess is not None,
            }
        )

    async def auth_setup(request: Request) -> JSONResponse:
        if not origin_ok(request):
            return _json_error("forbidden origin", 403)
        if store.count() > 0:
            return _json_error("setup already completed", 409)
        creds = parse_credentials(await body_json(request))
        if isinstance(creds, JSONResponse):
            return creds
        email, password = creds
        op = store.create(email, password)
        token, csrf = store.create_session(op)
        resp = JSONResponse({"operator": op.to_dict(), "csrf": csrf}, status_code=201)
        set_session_cookie(resp, token, request)
        return resp

    async def auth_login(request: Request) -> JSONResponse:
        if not origin_ok(request):
            return _json_error("forbidden origin", 403)
        creds = parse_credentials(await body_json(request))
        if isinstance(creds, JSONResponse):
            return creds
        email, password = creds
        op = store.authenticate(email, password)
        if not op:
            return _json_error("invalid credentials", 401)
        token, csrf = store.create_session(op)
        resp = JSONResponse({"operator": op.to_dict(), "csrf": csrf})
        set_session_cookie(resp, token, request)
        return resp

    async def auth_logout(request: Request) -> JSONResponse:
        token = read_session(request)
        if token:
            store.revoke_session(token)
        resp = JSONResponse({"ok": True})
        clear_session_cookie(resp)
        return resp

    async def auth_me(request: Request) -> JSONResponse:
        sess = _operator(request)
        if not sess:
            return _json_error("unauthorized", 401)
        op, csrf = sess
        return JSONResponse({"operator": op.to_dict(), "csrf": csrf})

    async def api_operators_list(request: Request) -> JSONResponse:
        op, err = await require_user(request)
        if err:
            return err
        return JSONResponse({"operators": [o.to_dict() for o in store.list_operators()]})

    async def api_operators_add(request: Request) -> JSONResponse:
        op, err = await require_user(request)
        if err:
            return err
        creds = parse_credentials(await body_json(request))
        if isinstance(creds, JSONResponse):
            return creds
        email, password = creds
        try:
            created = store.create(email, password)
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                return _json_error("email already exists", 409)
            raise
        return JSONResponse({"operator": created.to_dict()}, status_code=201)

    def _hub_status() -> dict:
        from ansible_flow_mcp.hub.enroll import hub_status

        try:
            data = hub_status(root=root)
            data["initialized"] = True
            return data
        except FileNotFoundError:
            return {
                "initialized": False,
                "root": str(root),
                "nodes": [],
                "groups": [],
                "spokes": [],
            }

    async def api_status(request: Request) -> JSONResponse:
        _, err = await require_user(request)
        if err:
            return err
        return JSONResponse(_hub_status())

    async def api_invite(request: Request) -> JSONResponse:
        _, err = await require_user(request)
        if err:
            return err
        from ansible_flow_mcp.cli import _parse_ttl
        from ansible_flow_mcp.hub.tokens import issue_token
        from ansible_flow_mcp.tui import build_spoke_join_command, default_join_hub

        body = await body_json(request)
        name = str(body.get("name") or "").strip()
        if not name:
            return _json_error("spoke name is required", 400)
        ttl = str(body.get("ttl") or "15m")
        join_hub = str(body.get("hub") or "").strip() or default_join_hub()
        addr = str(body.get("public_addr") or "").strip() or name
        try:
            issued = issue_token(name, ttl_seconds=_parse_ttl(ttl), root=root)
        except Exception as exc:
            return _json_error(str(exc), 400)
        cmd = build_spoke_join_command(
            token=issued.token, hub=join_hub, name=name, public_addr=addr
        )
        payload = issued.to_dict()
        payload["join_hub"] = join_hub
        payload["public_addr"] = addr
        payload["join_command"] = cmd
        return JSONResponse(payload)

    async def api_update_node(request: Request) -> JSONResponse:
        _, err = await require_user(request)
        if err:
            return err
        from ansible_flow_mcp.hub.enroll import update_node

        name = request.path_params["name"]
        body = await body_json(request)
        port = body.get("ansible_port")
        try:
            return JSONResponse(
                update_node(
                    name,
                    ansible_host=body.get("ansible_host"),
                    ansible_port=int(port) if port not in (None, "") else None,
                    ansible_user=body.get("ansible_user"),
                    root=root,
                )
            )
        except Exception as exc:
            return _json_error(str(exc), 400)

    async def api_revoke_node(request: Request) -> JSONResponse:
        _, err = await require_user(request)
        if err:
            return err
        from ansible_flow_mcp.hub.enroll import revoke_node

        name = request.path_params["name"]
        return JSONResponse(revoke_node(name, root=root))

    async def api_ping(request: Request) -> JSONResponse:
        _, err = await require_user(request)
        if err:
            return err
        from ansible_flow_mcp.ssh import spoke_call

        name = request.path_params["name"]
        try:
            result = spoke_call(name, tool="list_collections", root=root, timeout=30)
            return JSONResponse(result.to_dict())
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)

    async def api_groups(request: Request) -> JSONResponse:
        _, err = await require_user(request)
        if err:
            return err
        from ansible_flow_mcp.hub.enroll import list_groups_op

        try:
            return JSONResponse(list_groups_op(root=root))
        except FileNotFoundError:
            return JSONResponse({"ok": True, "groups": []})

    async def api_create_group(request: Request) -> JSONResponse:
        _, err = await require_user(request)
        if err:
            return err
        from ansible_flow_mcp.hub.enroll import create_group_op

        body = await body_json(request)
        name = str(body.get("name") or "").strip()
        if not name:
            return _json_error("group name is required", 400)
        try:
            return JSONResponse(create_group_op(name, root=root), status_code=201)
        except Exception as exc:
            return _json_error(str(exc), 400)

    async def api_delete_group(request: Request) -> JSONResponse:
        _, err = await require_user(request)
        if err:
            return err
        from ansible_flow_mcp.hub.enroll import delete_group_op

        name = request.path_params["name"]
        return JSONResponse(delete_group_op(name, root=root))

    async def api_set_members(request: Request) -> JSONResponse:
        _, err = await require_user(request)
        if err:
            return err
        from ansible_flow_mcp.hub.enroll import set_group_members_op

        name = request.path_params["name"]
        body = await body_json(request)
        hosts = body.get("members") or body.get("hosts") or []
        if isinstance(hosts, str):
            hosts = [h.strip() for h in hosts.split(",") if h.strip()]
        if not isinstance(hosts, list):
            return _json_error("members must be a list", 400)
        try:
            return JSONResponse(
                set_group_members_op(name, [str(h) for h in hosts], root=root)
            )
        except Exception as exc:
            return _json_error(str(exc), 400)

    async def api_hub_init(request: Request) -> JSONResponse:
        _, err = await require_user(request)
        if err:
            return err
        from ansible_flow_mcp.hub.state import hub_init

        body = await body_json(request)
        name = str(body.get("name") or "hub-01")
        st = hub_init(name=name, root=root)
        return JSONResponse(
            {"ok": True, "hub_id": st.hub_id, "name": st.name, "root": str(st.root)}
        )

    async def api_opencode(request: Request) -> JSONResponse:
        _, err = await require_user(request)
        if err:
            return err
        from ansible_flow_mcp.tui import App, write_opencode_hub_config

        path = write_opencode_hub_config(App(hub_root=root, hub_ok=True))
        return JSONResponse({"ok": True, "path": str(path)})

    def page(name: str):
        async def _inner(_request: Request) -> FileResponse:
            return FileResponse(STATIC / name)

        return _inner

    async def root_redirect(request: Request) -> RedirectResponse:
        sess = _operator(request)
        if store.count() == 0:
            return RedirectResponse("/setup", status_code=302)
        if not sess:
            return RedirectResponse("/login", status_code=302)
        return RedirectResponse("/console", status_code=302)

    async def static_file(request: Request) -> FileResponse | JSONResponse:
        rel = request.path_params["path"]
        if ".." in rel or rel.startswith("/"):
            return _json_error("not found", 404)
        target = (STATIC / rel).resolve()
        if not str(target).startswith(str(STATIC.resolve())) or not target.is_file():
            return _json_error("not found", 404)
        return FileResponse(target)

    routes = [
        Route("/", root_redirect),
        Route("/login", page("login.html")),
        Route("/setup", page("setup.html")),
        Route("/console", page("index.html")),
        Route("/static/{path:path}", static_file),
        Route("/api/auth/status", auth_status),
        Route("/api/auth/setup", auth_setup, methods=["POST"]),
        Route("/api/auth/login", auth_login, methods=["POST"]),
        Route("/api/auth/logout", auth_logout, methods=["POST"]),
        Route("/api/auth/me", auth_me),
        Route("/api/operators", api_operators_list, methods=["GET"]),
        Route("/api/operators", api_operators_add, methods=["POST"]),
        Route("/api/status", api_status),
        Route("/api/invite", api_invite, methods=["POST"]),
        Route("/api/nodes/{name}", api_update_node, methods=["POST"]),
        Route("/api/nodes/{name}", api_revoke_node, methods=["DELETE"]),
        Route("/api/nodes/{name}/ping", api_ping, methods=["POST"]),
        Route("/api/groups", api_groups, methods=["GET"]),
        Route("/api/groups", api_create_group, methods=["POST"]),
        Route("/api/groups/{name}", api_delete_group, methods=["DELETE"]),
        Route("/api/groups/{name}/members", api_set_members, methods=["POST"]),
        Route("/api/hub/init", api_hub_init, methods=["POST"]),
        Route("/api/opencode", api_opencode, methods=["POST"]),
    ]

    return Starlette(
        routes=routes,
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["*"],
                allow_headers=["*"],
            )
        ],
    )


def run_console(*, hub_root: Path | None = None, host: str = "127.0.0.1", port: int = 8785) -> None:
    import uvicorn

    app = create_app(hub_root)
    uvicorn.run(app, host=host, port=int(port), log_level="info")
