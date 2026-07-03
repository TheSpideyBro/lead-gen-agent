import asyncio
import logging
import os
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from aiohttp import web

from src.tracking.tracker import PIXEL_GIF, verify_signature
from src.outreach.email_sender import LeadScorer

logger = logging.getLogger(__name__)


# Per-IP sliding-window rate limit for the tracking pixel. Without this an
# attacker can poison a lead's open count by replaying the URL. See review S1.
_TRACK_WINDOW_SECONDS = 60
_TRACK_WINDOW_LIMIT = 10  # 10 requests per minute per IP is plenty for a real client


class _IPRateLimiter:
    def __init__(self) -> None:
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def allow(self, ip: str) -> bool:
        now = time.monotonic()
        async with self._lock:
            bucket = self._hits[ip]
            cutoff = now - _TRACK_WINDOW_SECONDS
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= _TRACK_WINDOW_LIMIT:
                return False
            bucket.append(now)
            return True


class TrackingServer:
    def __init__(self, db, host: str = None, port: int = None):
        """Initialize tracking server with secure defaults.
        
        Binds to 127.0.0.1 by default for security. Override with environment
        variables TRACKING_HOST and TRACKING_PORT if needed.
        """
        import os
        self.host = host or os.getenv("TRACKING_HOST", "127.0.0.1")
        self.port = port or int(os.getenv("TRACKING_PORT", "8080"))
        self.db = db
        self.host = host
        self.port = port
        self.scorer = LeadScorer()
        self._runner = None
        self._site = None
        self._limiter = _IPRateLimiter()

    async def _handle_pixel(self, request: web.Request) -> web.Response:
        lead_id = self._to_int(request.match_info.get("lead_id"))
        sequence_id = self._to_int(request.match_info.get("sequence_id"))
        signature = request.query.get("t", "")
        ip = (request.headers.get("X-Forwarded-For", request.remote or "")).split(",")[0].strip()

        # 1. Reject if the signature doesn't match.  Without this, anyone can
        #    inflate a lead's open count and bump its score by 15.  See S1.
        if not lead_id or not sequence_id or not verify_signature(lead_id, sequence_id, signature):
            # Return 200 + pixel anyway so the *legitimate* image is still
            # delivered; we simply don't record the open.  This avoids tipping
            # off spammers that there's a signature they need to forge.
            return self._pixel_response()

        # 2. Per-IP rate limit (defense in depth).
        if not await self._limiter.allow(ip):
            logger.warning("Tracking pixel rate limit hit: ip=%s", ip)
            return self._pixel_response()

        try:
            await self.db.log_email_open(lead_id, sequence_id, ip)
            await self.scorer.rescore_opened_lead(self.db, lead_id)
            logger.info("Email open: lead=%s sequence=%s ip=%s", lead_id, sequence_id, ip)
        except Exception as exc:
            # Don't echo the IP/lead into a structured log on the same line
            # as the error; keep them as separate fields.
            logger.error("Failed to log email open: %s", type(exc).__name__,
                         extra={"lead_id": lead_id, "sequence_id": sequence_id})

        return self._pixel_response()

    def _pixel_response(self) -> web.Response:
        return web.Response(
            body=PIXEL_GIF,
            content_type="image/gif",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, private"},
        )

    @staticmethod
    def _to_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    async def start(self):
        app = web.Application()
        app.router.add_get("/track/{lead_id}/{sequence_id}.png", self._handle_pixel)
        
        # A5 fix: Add health check endpoint for container orchestration
        async def health_check(request: web.Request) -> web.Response:
            return web.json_response({"status": "ok", "service": "tracking"})
        app.router.add_get("/health", health_check)
        
        # S9 fix: Add security middleware
        async def add_security_headers(request: web.Request, handler):
            response = await handler(request)
            response.headers.update({
                "Content-Security-Policy": "default-src 'none'",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
            })
            return response
        app.middlewares.append(add_security_headers)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        logger.info("Tracking server listening on %s:%s (secure: bound to localhost)", self.host, self.port)

    async def stop(self):
        # Shutdown cleanly even if start() raised mid-way.
        if self._site is not None:
            try:
                await self._site.stop()
            except Exception:
                pass
            self._site = None
        if self._runner is not None:
            try:
                await self._runner.cleanup()
            except Exception:
                pass
            self._runner = None


def get_tracking_port() -> int:
    base = os.getenv("TRACKING_BASE_URL", "http://localhost:8080")
    try:
        return int(base.rstrip("/").rsplit(":", 1)[-1])
    except (ValueError, IndexError):
        return 8080
