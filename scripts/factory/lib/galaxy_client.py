"""Ansible Galaxy HTTP client — top collections + module inventory."""
from __future__ import annotations

import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable

from .http_util import http_get_json
from .proxy_pool import ProxyPool


@dataclass
class CollectionHit:
    namespace: str
    name: str
    download_count: int = 0
    description: str = ""
    latest_version: str = ""
    deprecated: bool = False
    tags: list[str] = field(default_factory=list)
    modules: list[dict[str, str]] = field(default_factory=list)

    @property
    def fqcn(self) -> str:
        return f"{self.namespace}.{self.name}"


class GalaxyClient:
    def __init__(
        self,
        base: str = "https://galaxy.ansible.com",
        *,
        timeout: float = 45.0,
        pause: float = 0.15,
        user_agent: str = "ansible-flow-mcp-factory/0.1",
        use_proxy: bool = False,
        proxy: str | None = None,
        proxy_pool: ProxyPool | None = None,
        retries: int = 3,
    ) -> None:
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.pause = pause
        self.user_agent = user_agent
        self.use_proxy = use_proxy
        self.proxy = proxy  # fixed proxy URL
        self.proxy_pool = proxy_pool
        self.retries = max(1, retries)

    def _pick_proxy(self) -> str | None:
        if not self.use_proxy:
            return None
        if self.proxy:
            return self.proxy
        if self.proxy_pool:
            return self.proxy_pool.acquire()
        return None

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        q = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
        url = f"{self.base}{path}"
        if q:
            url = f"{url}?{q}"
        last_err: Exception | None = None
        for attempt in range(self.retries):
            proxy = self._pick_proxy()
            try:
                data = http_get_json(
                    url,
                    headers={"User-Agent": self.user_agent, "Accept": "application/json"},
                    timeout=self.timeout,
                    proxy=proxy,
                )
                if proxy and self.proxy_pool:
                    self.proxy_pool.report_ok(proxy)
                if self.pause:
                    time.sleep(self.pause)
                if not isinstance(data, dict):
                    raise RuntimeError(f"Unexpected Galaxy payload type: {type(data)}")
                return data
            except Exception as e:
                last_err = e
                if proxy and self.proxy_pool:
                    self.proxy_pool.report_bad(proxy)
                time.sleep(0.3 * (attempt + 1))
        raise RuntimeError(f"Galaxy GET failed {url}: {last_err}") from last_err

    def search_top_collections(
        self,
        *,
        limit: int = 40,
        page_size: int = 20,
        min_download_count: int = 0,
        namespaces: set[str] | None = None,
        keywords: str = "",
        progress: Callable[[str], None] | None = None,
    ) -> list[CollectionHit]:
        """Ranked by download_count via Galaxy UI search API."""
        out: list[CollectionHit] = []
        offset = 0
        page_size = max(5, min(100, page_size))
        while len(out) < limit:
            batch = min(page_size, limit - len(out) + 10)
            data = self._get(
                "/api/_ui/v1/search/",
                {
                    "keywords": keywords or "",
                    "order_by": "-download_count",
                    "type": "collection",
                    "page_size": batch,
                    "limit": batch,
                    "offset": offset,
                },
            )
            rows = data.get("data") or []
            if not rows:
                break
            if progress:
                total = (data.get("meta") or {}).get("count")
                px = "proxy" if self.use_proxy else "direct"
                progress(f"galaxy[{px}] offset={offset} got={len(rows)} total≈{total}")
            for item in rows:
                hit = self._parse_search_item(item)
                if hit.deprecated:
                    continue
                if hit.download_count < min_download_count:
                    continue
                if namespaces and hit.namespace not in namespaces:
                    continue
                out.append(hit)
                if len(out) >= limit:
                    break
            offset += len(rows)
            links = data.get("links") or {}
            if not links.get("next"):
                break
        return out[:limit]

    def _parse_search_item(self, item: dict[str, Any]) -> CollectionHit:
        ns = item.get("namespace")
        if isinstance(ns, dict):
            namespace = str(ns.get("name") or "")
        else:
            namespace = str(ns or "")
        name = str(item.get("name") or "")
        latest = item.get("latest_version")
        if isinstance(latest, dict):
            ver = str(latest.get("version") or "")
        else:
            ver = str(latest or "")
        modules: list[dict[str, str]] = []
        for c in item.get("contents") or []:
            if not isinstance(c, dict):
                continue
            if str(c.get("content_type") or "") != "module":
                continue
            mname = str(c.get("name") or "").strip()
            if not mname:
                continue
            modules.append(
                {
                    "name": mname,
                    "description": str(c.get("description") or "")[:500],
                }
            )
        tags = []
        for t in item.get("tags") or []:
            if isinstance(t, dict):
                tags.append(str(t.get("name") or t.get("tag") or ""))
            else:
                tags.append(str(t))
        return CollectionHit(
            namespace=namespace,
            name=name,
            download_count=int(item.get("download_count") or 0),
            description=str(item.get("description") or "")[:500],
            latest_version=ver,
            deprecated=bool(item.get("deprecated")),
            tags=[t for t in tags if t],
            modules=modules,
        )

    def collection_detail(self, namespace: str, name: str) -> dict[str, Any]:
        return self._get(
            f"/api/v3/plugin/ansible/content/published/collections/index/{namespace}/{name}/"
        )


def modules_from_hits(
    hits: list[CollectionHit],
    *,
    modules_per_collection: int = 0,
    deny: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Flatten collection hits → module rows with FQCN + rank metadata."""
    deny = deny or set()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rank, hit in enumerate(hits, start=1):
        mods = list(hit.modules)
        if modules_per_collection and modules_per_collection > 0:
            mods = mods[:modules_per_collection]
        for m in mods:
            fqcn = f"{hit.namespace}.{hit.name}.{m['name']}"
            if fqcn in seen or fqcn in deny:
                continue
            seen.add(fqcn)
            rows.append(
                {
                    "fqcn": fqcn,
                    "shortName": m["name"],
                    "collection": hit.fqcn,
                    "description": m.get("description") or hit.description or m["name"],
                    "downloadCount": hit.download_count,
                    "collectionRank": rank,
                    "collectionVersion": hit.latest_version,
                    "source": "galaxy",
                }
            )
    rows.sort(key=lambda r: (-int(r.get("downloadCount") or 0), str(r["fqcn"])))
    return rows


def client_from_settings(settings: dict[str, Any], pool: ProxyPool | None = None) -> GalaxyClient:
    use_proxy = bool(settings.get("useProxy"))
    fixed = str(settings.get("proxy") or "").strip() or None
    return GalaxyClient(
        base=str(settings.get("galaxyBase") or "https://galaxy.ansible.com"),
        timeout=float(settings.get("httpTimeout") or 45),
        pause=float(settings.get("galaxyPause") or 0.15),
        use_proxy=use_proxy,
        proxy=fixed,
        proxy_pool=pool if use_proxy and not fixed else None,
        retries=int(settings.get("httpRetries") or 3),
    )
