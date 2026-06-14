"""WhatsApp Business API client (360dialog) with an inbound webhook receiver.

GLOBAL-specific: the Playwright WhatsApp-Web bot only works for one logged-in
number and is fragile at scale. The WhatsApp Business API (via 360dialog as the
BSP) sends to any country code reliably and receives messages over a webhook.

Reality check: WhatsApp Business API is NOT free — it needs a Meta-approved
WhatsApp Business Account and a paid 360dialog number; template messages must be
pre-approved. This client is fully functional but inert until D360_API_KEY and
D360_PHONE_NUMBER_ID are configured. When they aren't, callers fall back to the
Playwright bot via select_whatsapp_provider().
"""
import logging
import os
import re
from typing import List, Optional

import aiohttp
from aiohttp import web

from src.utils.api_usage import APIUsageTracker

logger = logging.getLogger(__name__)

# 360dialog cloud API (WhatsApp Cloud payload format). Override via D360_BASE_URL.
DEFAULT_BASE_URL = "https://waba-v2.360dialog.io"
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)


class WhatsAppAPI:
    SOURCE = "d360"

    def __init__(self, db=None, ai=None):
        self.api_key = os.getenv("D360_API_KEY", "")
        self.phone_number_id = os.getenv("D360_PHONE_NUMBER_ID", "")
        self.base_url = os.getenv("D360_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
        self.calendly_link = os.getenv("CALENDLY_LINK", "")
        self.db = db
        self.ai = ai
        self.usage = APIUsageTracker()
        self._webhook_runner = None

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict:
        return {"D360-API-KEY": self.api_key, "Content-Type": "application/json"}

    @staticmethod
    def format_phone(phone: str) -> str:
        """Normalize any international number to digits-only E.164 (no '+')."""
        digits = re.sub(r"\D", "", phone or "")
        return digits

    # ----- outbound -----------------------------------------------------------

    async def send_message(self, phone: str, message: str) -> bool:
        if not self.is_configured():
            logger.warning("360dialog: D360_API_KEY not set — cannot send")
            return False
        if not self.usage.can_spend(self.SOURCE):
            logger.warning("360dialog: daily quota reached — skipping send")
            return False

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self.format_phone(phone),
            "type": "text",
            "text": {"body": message},
        }
        return await self._post_message(payload)

    async def send_template(self, phone: str, template_name: str,
                            params: List[str], lang_code: str = "en") -> bool:
        if not self.is_configured():
            logger.warning("360dialog: D360_API_KEY not set — cannot send template")
            return False

        components = []
        if params:
            components.append({
                "type": "body",
                "parameters": [{"type": "text", "text": str(p)} for p in params],
            })
        payload = {
            "messaging_product": "whatsapp",
            "to": self.format_phone(phone),
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": lang_code},
                "components": components,
            },
        }
        return await self._post_message(payload)

    async def _post_message(self, payload: dict) -> bool:
        url = f"{self.base_url}/messages"
        try:
            async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
                async with session.post(url, json=payload, headers=self._headers()) as resp:
                    self.usage.record(self.SOURCE)
                    if resp.status in (200, 201):
                        logger.info("360dialog: message sent to %s", payload.get("to"))
                        return True
                    logger.warning("360dialog send HTTP %s — %s", resp.status,
                                   (await resp.text())[:200])
                    return False
        except Exception as exc:
            logger.error("360dialog send failed: %s", exc)
            return False

    # ----- inbound webhook ----------------------------------------------------

    async def start_webhook(self, host: str = "0.0.0.0", port: int = 8081):
        """Run a lightweight aiohttp server that receives inbound messages."""
        app = web.Application()
        app.router.add_post("/webhook", self.handle_webhook)
        app.router.add_get("/webhook", lambda r: web.Response(text="ok"))  # verification
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        self._webhook_runner = runner
        logger.info("360dialog webhook listening on %s:%d/webhook", host, port)

    async def stop_webhook(self):
        if self._webhook_runner:
            await self._webhook_runner.cleanup()
            self._webhook_runner = None

    async def handle_webhook(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            return web.Response(status=400, text="bad json")

        for msg in self._extract_messages(data):
            try:
                await self._process_incoming(msg["from"], msg["text"])
            except Exception as exc:
                logger.error("webhook processing error: %s", exc)
        return web.Response(text="ok")

    @staticmethod
    def _extract_messages(data: dict) -> List[dict]:
        """Pull (from, text) pairs out of the WhatsApp Cloud webhook shape."""
        out = []
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for m in value.get("messages", []):
                    text = (m.get("text") or {}).get("body", "")
                    if m.get("from") and text:
                        out.append({"from": m["from"], "text": text})
        return out

    async def _process_incoming(self, phone: str, text: str):
        classification = await self._classify(text)
        lead_id = await self._lead_id_by_phone(phone)
        await self._store_response(lead_id, phone, text, classification)

        if classification == "interested":
            if self.calendly_link:
                await self.send_message(phone, f"Great! Book a quick call: {self.calendly_link}")
            if lead_id and self.db:
                await self.db.update_lead_status(lead_id, "qualified")
        elif classification == "question":
            answer = await self._answer(text)
            await self.send_message(phone, answer)
        elif classification == "stop":
            if lead_id and self.db:
                await self.db.update_lead_status(lead_id, "unsubscribed")
                await self.db.stop_all_sequences(lead_id)

    async def _classify(self, message: str) -> str:
        if not self.ai:
            return "question"
        prompt = (f'Classify this WhatsApp message as exactly one word: '
                  f'interested, question, not_interested, stop.\n\nMessage: "{message}"')
        try:
            result = await self.ai.generate(prompt, "You are a message classifier.")
            word = result.strip().lower().split()[0]
            return word if word in {"interested", "question", "not_interested", "stop"} else "question"
        except Exception:
            return "question"

    async def _answer(self, question: str) -> str:
        if not self.ai:
            return "Thanks for your message! I'll follow up shortly."
        try:
            return (await self.ai.generate(
                f'Answer this prospect question briefly (<100 words):\n"{question}"',
                "You are a helpful sales rep."))[:500]
        except Exception:
            return "Thanks for your message! I'll follow up shortly."

    async def _lead_id_by_phone(self, phone: str) -> Optional[int]:
        if not self.db:
            return None
        cursor = await self.db.db.execute(
            "SELECT id FROM leads WHERE phone LIKE ? LIMIT 1", (f"%{phone[-9:]}%",))
        row = await cursor.fetchone()
        return row[0] if row else None

    async def _store_response(self, lead_id, phone, body, classification):
        if not self.db:
            return
        await self.db.db.execute(
            "INSERT INTO whatsapp_responses (lead_id, phone, body, classification) "
            "VALUES (?, ?, ?, ?)", (lead_id, phone, body, classification))
        await self.db.db.commit()

    async def close(self):
        await self.stop_webhook()


def select_whatsapp_provider(db=None, ai=None):
    """Return the configured WhatsApp provider.

    WHATSAPP_PROVIDER=api (and D360 configured) -> WhatsAppAPI; otherwise the
    Playwright WhatsApp-Web bot. Lets the rest of the app stay provider-agnostic.
    """
    provider = os.getenv("WHATSAPP_PROVIDER", "web").lower()
    if provider == "api" and os.getenv("D360_API_KEY"):
        logger.info("WhatsApp provider: 360dialog API")
        api = WhatsAppAPI(db=db, ai=ai)
        return api
    from src.whatsapp_bot import WhatsAppBot  # lazy import to avoid hard dep
    logger.info("WhatsApp provider: Playwright WhatsApp Web (fallback)")
    bot = WhatsAppBot()
    bot.db = db
    bot.ai = ai
    return bot
