"""Rotating proxy pool for scrapers (global IP rotation).

GLOBAL-specific: scraping international sources from one IP gets rate-limited or
blocked. PROXY_LIST (comma-separated ip:port:user:pass) is rotated per request;
on failure we fall back to a direct connection and log per-proxy success rates.
"""
import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)


class ProxyManager:
    def __init__(self, proxy_list_env: str = "PROXY_LIST"):
        self.proxies: List[str] = self._parse(os.getenv(proxy_list_env, ""))
        self._idx = 0
        # proxy_url -> {"success": int, "fail": int}
        self.stats = {p: {"success": 0, "fail": 0} for p in self.proxies}

    def _parse(self, raw: str) -> List[str]:
        out = []
        for entry in raw.split(","):
            entry = entry.strip()
            if not entry:
                continue
            parts = entry.split(":")
            if len(parts) == 4:
                ip, port, user, pw = parts
                out.append(f"http://{user}:{pw}@{ip}:{port}")
            elif len(parts) == 2:
                ip, port = parts
                out.append(f"http://{ip}:{port}")
            else:
                logger.warning("Ignoring malformed proxy entry: %s", entry)
        return out

    def has_proxies(self) -> bool:
        return bool(self.proxies)

    def next_proxy(self) -> Optional[str]:
        """Round-robin the pool. Returns None when no proxies configured
        (caller should then connect directly)."""
        if not self.proxies:
            return None
        proxy = self.proxies[self._idx % len(self.proxies)]
        self._idx += 1
        return proxy

    def record(self, proxy: Optional[str], success: bool):
        if not proxy or proxy not in self.stats:
            return
        self.stats[proxy]["success" if success else "fail"] += 1

    def performance(self) -> dict:
        """Per-proxy success rate for monitoring."""
        report = {}
        for proxy, s in self.stats.items():
            total = s["success"] + s["fail"]
            rate = round(100 * s["success"] / total, 1) if total else None
            # Mask credentials in the report key.
            masked = proxy.split("@")[-1] if "@" in proxy else proxy
            report[masked] = {"success": s["success"], "fail": s["fail"], "rate_pct": rate}
        return report
