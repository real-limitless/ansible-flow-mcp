"""HTTP helpers with optional SOCKS5/HTTP proxy (httpx preferred)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

_HAS_HTTPX = False
try:
    import httpx

    _HAS_HTTPX = True
except ImportError:
    httpx = None  # type: ignore


def http_get_text(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 45.0,
    proxy: str | None = None,
    follow_redirects: bool = True,
) -> str:
    """GET url → text. proxy e.g. socks5://host:port or http://host:port."""
    hdrs = {
        "User-Agent": "ansible-flow-mcp-factory/0.1",
        "Accept": "*/*",
        **(headers or {}),
    }
    # env fallback when no explicit proxy
    if not proxy:
        proxy = (
            os.environ.get("ALL_PROXY")
            or os.environ.get("HTTPS_PROXY")
            or os.environ.get("HTTP_PROXY")
            or os.environ.get("all_proxy")
            or os.environ.get("https_proxy")
            or os.environ.get("http_proxy")
            or None
        )

    if _HAS_HTTPX:
        kwargs: dict[str, Any] = {
            "timeout": timeout,
            "follow_redirects": follow_redirects,
            "headers": hdrs,
        }
        if proxy:
            kwargs["proxy"] = proxy
        with httpx.Client(**kwargs) as client:
            r = client.get(url)
            r.raise_for_status()
            return r.text

    # stdlib path — HTTP(S) proxy only (no SOCKS without httpx/PySocks)
    handlers = []
    if proxy:
        if proxy.startswith("socks"):
            raise RuntimeError(
                "SOCKS proxy requires httpx: pip install 'httpx[socks]' "
                f"(got {proxy!r})"
            )
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers) if handlers else urllib.request.build_opener()
    req = urllib.request.Request(url, headers=hdrs)
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"HTTP {e.code} {url}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error {url}: {e}") from e


def http_get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 45.0,
    proxy: str | None = None,
) -> Any:
    text = http_get_text(
        url,
        headers={**(headers or {}), "Accept": "application/json"},
        timeout=timeout,
        proxy=proxy,
    )
    return json.loads(text)
