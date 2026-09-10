from __future__ import annotations

import re
from urllib.parse import urlparse

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

COOKIE = "af_op"
SESSION_MAX_AGE = 7 * 24 * 3600
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def parse_credentials(body: dict) -> tuple[str, str] | JSONResponse:
    email = str(body.get("email") or "").strip().lower()
    password = str(body.get("password") or "")
    if not EMAIL_RE.match(email):
        return JSONResponse({"error": "invalid email"}, status_code=400)
    if len(password) < 8:
        return JSONResponse(
            {"error": "password must be at least 8 characters"}, status_code=400
        )
    return email, password


def origin_ok(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return True
    host = request.headers.get("host") or ""
    try:
        return urlparse(origin).netloc == host
    except ValueError:
        return False


def set_session_cookie(response: Response, token: str, request: Request) -> None:
    secure = request.url.scheme == "https"
    response.set_cookie(
        COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
        secure=secure,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def read_session(request: Request) -> str:
    return (request.cookies.get(COOKIE) or "").strip()
