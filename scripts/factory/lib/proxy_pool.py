"""SOCKS5/HTTP proxy pool: refresh list, health-check, rotate."""
from __future__ import annotations

import json
import random
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .http_util import http_get_text
from .paths import JOBS

DEFAULT_PROXY_URL = "https://databay.com/free-proxy-list/socks5.txt"
# host:port or scheme://host:port
LINE_RE = re.compile(
    r"^(?:(?P<scheme>socks5h?|socks4|https?)://)?"
    r"(?P<host>\d{1,3}(?:\.\d{1,3}){3}|[a-zA-Z0-9.-]+)"
    r":(?P<port>\d{2,5})\s*$"
)
HEALTH_URLS = (
    "https://galaxy.ansible.com/api/",
    "https://httpbin.org/ip",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ProxyPool:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or JOBS
        self.dir = self.root / "proxies"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.list_path = self.dir / "proxies.txt"
        self.health_path = self.dir / "health.json"
        self._lock = threading.RLock()
        self._alive: list[str] = []
        self._dead: set[str] = set()
        self._fail_counts: dict[str, int] = {}
        self._load_health()

    def _load_health(self) -> None:
        if not self.health_path.is_file():
            return
        try:
            data = json.loads(self.health_path.read_text(encoding="utf-8"))
            self._alive = list(data.get("alive") or [])
            self._dead = set(data.get("dead") or [])
            self._fail_counts = {
                str(k): int(v) for k, v in (data.get("failCounts") or {}).items()
            }
        except Exception:
            pass

    def save_health(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "alive": self._alive,
            "dead": sorted(self._dead),
            "failCounts": self._fail_counts,
            "updatedAt": _now(),
            "counts": {
                "alive": len(self._alive),
                "dead": len(self._dead),
                "listed": self.count_listed(),
            },
        }
        self.health_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def count_listed(self) -> int:
        return len(self.listed_proxies())

    def parse_proxy_lines(self, text: str, *, default_scheme: str = "socks5") -> list[str]:
        out: list[str] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = LINE_RE.match(line)
            if not m:
                continue
            scheme = m.group("scheme") or default_scheme
            # prefer socks5h (DNS via proxy) when plain socks5
            if scheme == "socks5":
                scheme = "socks5h"
            url = f"{scheme}://{m.group('host')}:{m.group('port')}"
            out.append(url)
        seen: set[str] = set()
        uniq: list[str] = []
        for p in out:
            if p not in seen:
                seen.add(p)
                uniq.append(p)
        return uniq

    def refresh(
        self,
        source_url: str | None = None,
        *,
        local_file: Path | None = None,
        proxy_for_fetch: str | None = None,
    ) -> int:
        if local_file and local_file.exists():
            text = local_file.read_text(encoding="utf-8", errors="ignore")
        else:
            url = source_url or DEFAULT_PROXY_URL
            text = http_get_text(url, timeout=30.0, proxy=proxy_for_fetch)
        proxies = self.parse_proxy_lines(text)
        body = "# proxy list (host:port)\n" + "\n".join(
            p.split("://", 1)[-1] for p in proxies
        ) + "\n"
        self.list_path.write_text(body, encoding="utf-8")
        with self._lock:
            listed = set(proxies)
            self._alive = [p for p in self._alive if p in listed]
            self._dead = {p for p in self._dead if p in listed}
        self.save_health()
        return len(proxies)

    def listed_proxies(self) -> list[str]:
        if not self.list_path.is_file():
            return []
        return self.parse_proxy_lines(
            self.list_path.read_text(encoding="utf-8", errors="ignore")
        )

    def add_proxy(self, proxy: str) -> None:
        """Append a single proxy URL or host:port to the list."""
        parsed = self.parse_proxy_lines(proxy.strip())
        if not parsed:
            # try as host:port
            parsed = self.parse_proxy_lines(proxy.strip().split("://")[-1])
        if not parsed:
            raise ValueError(f"Invalid proxy: {proxy!r}")
        existing = self.listed_proxies()
        for p in parsed:
            if p not in existing:
                existing.append(p)
        body = "# proxy list\n" + "\n".join(x.split("://", 1)[-1] for x in existing) + "\n"
        self.list_path.write_text(body, encoding="utf-8")
        with self._lock:
            for p in parsed:
                if p not in self._alive:
                    self._alive.append(p)
                self._dead.discard(p)
        self.save_health()

    def probe_one(self, proxy_url: str, timeout: float = 10.0) -> bool:
        for health in HEALTH_URLS:
            try:
                text = http_get_text(health, timeout=timeout, proxy=proxy_url)
                if text and len(text) > 2:
                    return True
            except Exception:
                continue
        return False

    def health_check(
        self,
        *,
        limit: int = 40,
        timeout: float = 10.0,
        workers: int = 12,
    ) -> dict[str, Any]:
        listed = self.listed_proxies()
        if not listed:
            return {"alive": 0, "dead": 0, "probed": 0, "probeAlive": 0, "probeDead": 0}
        sample = listed[:]
        random.shuffle(sample)
        sample = sample[: max(1, limit)]
        alive: list[str] = []
        dead: list[str] = []
        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            futs = {ex.submit(self.probe_one, p, timeout): p for p in sample}
            for fut in as_completed(futs):
                p = futs[fut]
                ok = False
                try:
                    ok = bool(fut.result())
                except Exception:
                    ok = False
                (alive if ok else dead).append(p)
        with self._lock:
            for p in alive:
                if p not in self._alive:
                    self._alive.append(p)
                self._dead.discard(p)
                self._fail_counts.pop(p, None)
            for p in dead:
                self._alive = [x for x in self._alive if x != p]
                self._dead.add(p)
        self.save_health()
        return {
            "alive": len(self._alive),
            "dead": len(self._dead),
            "probed": len(sample),
            "probeAlive": len(alive),
            "probeDead": len(dead),
            "updatedAt": _now(),
        }

    def acquire(self) -> str | None:
        with self._lock:
            if self._alive:
                return random.choice(self._alive)
            listed = self.listed_proxies()
            if not listed:
                return None
            return random.choice(listed)

    def report_ok(self, proxy_url: str) -> None:
        with self._lock:
            self._fail_counts.pop(proxy_url, None)
            self._dead.discard(proxy_url)
            if proxy_url not in self._alive:
                self._alive.append(proxy_url)

    def report_bad(self, proxy_url: str, *, max_fails: int = 3) -> None:
        with self._lock:
            n = self._fail_counts.get(proxy_url, 0) + 1
            self._fail_counts[proxy_url] = n
            if n >= max_fails:
                self._alive = [p for p in self._alive if p != proxy_url]
                self._dead.add(proxy_url)
        if random.random() < 0.25:
            self.save_health()

    def summary(self) -> dict[str, Any]:
        return {
            "listed": self.count_listed(),
            "alive": len(self._alive),
            "dead": len(self._dead),
            "listPath": str(self.list_path),
            "healthPath": str(self.health_path),
        }
