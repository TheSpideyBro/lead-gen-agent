# AGENT_OWNER: analytics-001
# TASK_ID: 3af35379-03e4-4cf8-9536-263456dac75b
import logging
import os

from aiohttp import web

from src.tracking.tracker import PIXEL_GIF
from src.outreach.email_sender import LeadScorer

logger = logging.getLogger(__name__)


class TrackingServer:
    def __init__(self, db, host: str = "0.0.0.0", port: int = 8080):
        self.db = db
        self.host = host
        self.port = port
        self.scorer = LeadScorer()
        self._runner = None

    async def _handle_pixel(self, request: web.Request) -> web.Response:
        lead_id = self._to_int(request.match_info.get("lead_id"))
        sequence_id = self._to_int(request.match_info.get("sequence_id"))
        ip = request.headers.get("X-Forwarded-For", request.remote or "")

        try:
            await self.db.log_email_open(lead_id, sequence_id, ip)
            if lead_id is not None:
                await self.scorer.rescore_opened_lead(self.db, lead_id)
            logger.info(f"Email open: lead={lead_id} sequence={sequence_id} ip={ip}")
        except Exception as exc:
            logger.error(f"Failed to log email open: {exc}")

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
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        logger.info(f"Tracking server listening on {self.host}:{self.port}")

    async def stop(self):
        if self._runner:
            await self._runner.cleanup()
            self._runner = None


def get_tracking_port() -> int:
    base = os.getenv("TRACKING_BASE_URL", "http://localhost:8080")
    try:
        return int(base.rstrip("/").rsplit(":", 1)[-1])
    except (ValueError, IndexError):
        return 8080
