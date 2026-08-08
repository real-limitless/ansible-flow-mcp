"""Ansible Galaxy HTTP client — top collections + module inventory."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable


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
    ) -> None:
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.pause = pause
        self.user_agent = user_agent

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        q = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
        url = f"{self.base}{path}"
        if q:
            url = f"{url}?{q}"
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": self.user_agent,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"Galaxy HTTP {e.code} {url}: {body}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Galaxy network error {url}: {e}") from e
        if self.pause:
            time.sleep(self.pause)
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise RuntimeError(f"Unexpected Galaxy payload type: {type(data)}")
        return data

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
                progress(f"galaxy offset={offset} got={len(rows)} total≈{total}")
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
