import asyncio
import logging
import os
from pathlib import Path
from typing import Optional, List

from playwright.async_api import async_playwright

from src.utils.validators import validate_phone, sanitize_string

logger = logging.getLogger(__name__)


class WhatsAppBot:
    SELECTORS = {
        "chat_list": '[aria-label="Chat list"]',
        "message_input": '[aria-label="Type a message"]',
        "unread_chats": '[role="textbox"][data-tab="10"]',
    }

    @staticmethod
    def _html_escape(text: str) -> str:
        # WhatsApp Web is mostly tolerant of plaintext, but the LLM
        # sometimes returns HTML and we previously filled the input
        # verbatim, which showed up as broken formatting in the recipient's
        # client.  We also use this in any place that builds a string
        # from untrusted (LLM-derived) text.  See code review S4.
        if not text:
            return ""
        # Build entities at runtime so the diff tool doesn't strip them.
        amp = chr(38) + "amp;"
        lt = chr(38) + "lt;"
        gt = chr(38) + "gt;"
        quot = chr(38) + "quot;"
        return (
            text.replace(chr(38), amp)
                .replace(chr(60), lt)
                .replace(chr(62), gt)
                .replace(chr(34), quot)
        )

    def __init__(self, data_dir: str = "data/whatsapp"):
        self.data_dir = Path(os.getenv("WHATSAPP_DATA_DIR", data_dir))
        self.data_dir = Path(__file__).parent.parent / self.data_dir if not self.data_dir.is_absolute() else self.data_dir
        self.playwright = None
        self.browser = None
        self.page = None
        self.db = None
        self.ai = None
        self.calendly_link = os.getenv("CALENDLY_LINK", "")
        self.owner_phone = os.getenv("OWNER_PHONE", "")

    async def start(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.data_dir),
            headless=os.getenv("WHATSAPP_HEADLESS", "false").lower() == "true",
        )
        self.page = await self.browser.new_page()
        await self.page.goto("https://web.whatsapp.com")
        await self._wait_for_login()

    async def _wait_for_login(self):
        try:
            await self.page.wait_for_selector(self.SELECTORS["chat_list"], timeout=60000)
            logger.info("WhatsApp Web logged in")
        except Exception:
            logger.warning("Please scan QR code to log in")
            await asyncio.to_thread(input, "Press Enter after scanning QR code...")

    def _format_phone(self, phone: str) -> str:
        # Prefer the `phonenumbers` library if available — it knows about
        # E.164 and the target countries in config/agency_profile.json
        # (US/UK/CA/AU/DE/UAE/SG) and will not silently misroute prospects
        # the way the previous "prepend 1 to any 10 digits" hack did.
        # See code review B9 / S9.
        phone = sanitize_string(phone).replace("+", "").replace("-", "").replace(" ", "")
        try:
            import phonenumbers  # type: ignore
            for region in ("US", "GB", "CA", "AU", "DE", "AE", "SG", None):
                try:
                    parsed = phonenumbers.parse("+" + phone if not phone.startswith("+") else phone,
                                                 region)
                    if phonenumbers.is_valid_number(parsed):
                        return str(parsed.country_code) + str(parsed.national_number)
                except Exception:
                    continue
        except ImportError:
            pass
        # Fallback: require a 7–15 digit E.164 body; do NOT auto-prepend 1.
        if 7 <= len(phone) <= 15 and phone.isdigit():
            return phone
        raise ValueError(f"Cannot normalize phone number: {phone!r}")

    async def send_message(self, phone: str, message: str) -> bool:
        if not validate_phone(phone):
            logger.warning("Invalid phone number: %r", phone)
            return False

        try:
            phone = self._format_phone(phone)
            url = f"https://web.whatsapp.com/send?phone={phone}"
            await self.page.goto(url, timeout=30000)

            await self.page.wait_for_selector(self.SELECTORS["message_input"], timeout=15000)
            await self.page.fill(self.SELECTORS["message_input"], self._html_escape(sanitize_string(message, 1000)))
            await self.page.keyboard.press("Enter")

            await asyncio.sleep(1)
            logger.info("Message sent", extra={"to_digits_len": len(phone)})
            return True
        except Exception as exc:
            # Don't echo the prospect's phone number in the log line.
            # See review S5.
            logger.error("Failed to send WhatsApp: %s", type(exc).__name__)
            return False

    async def poll_new_messages(self) -> int:
        if not self.page or not self.db:
            logger.warning("WhatsApp not connected or DB not set")
            return 0

        processed = 0
        try:
            chat_elements = await self.page.query_selector_all(self.SELECTORS["unread_chats"])
            for elem in chat_elements:
                await elem.click()
                await asyncio.sleep(1)

                messages = await self.get_new_messages()
                if not messages:
                    continue

                latest_msg = messages[-1]
                # Phone now comes from the chat header, not from the URL. The
                # previous split("phone=") raised IndexError when the chat was
                # opened from the sidebar (no phone= query param). See B6.
                phone = await self._extract_phone_from_header() or ""

                lead_id = await self._get_lead_id_by_phone(phone)
                classification = await self._classify_incoming(latest_msg)
                await self._store_whatsapp_response(lead_id, phone, latest_msg, classification)

                if classification == "interested":
                    if self.calendly_link:
                        await self.send_message(phone, f"I'd love to discuss how I can help! Book a call: {self.calendly_link}")
                    if lead_id:
                        await self.db.update_lead_status(lead_id, "qualified")
                    processed += 1

                elif classification == "question":
                    lead = await self.db.get_lead_by_id(lead_id) if lead_id else {}
                    response = await self._generate_answer(latest_msg, lead)
                    await self.send_message(phone, response)
                    processed += 1

                # The unified vocabulary uses `not_interested` (not `stop`).
                # We still accept `stop` for back-compat with prior training.
                elif classification in ("stop", "not_interested"):
                    if lead_id:
                        await self.db.update_lead_status(lead_id, "unsubscribed")
                        await self.db.stop_all_sequences(lead_id)
                    processed += 1

        except Exception as exc:
            logger.error("WhatsApp polling failed: %s", type(exc).__name__)

        return processed

    async def _extract_phone_from_header(self) -> Optional[str]:
        """Read the phone number from the open chat's header element.

        The previous implementation parsed `phone=` from `self.page.url`,
        which is empty for chats opened by clicking the sidebar. See B6.
        """
        if not self.page:
            return None
        # Fall back to the URL for chats opened via the wa.me/send flow.
        url_phone = ""
        if "phone=" in self.page.url:
            try:
                url_phone = self.page.url.split("phone=", 1)[1].split("&", 1)[0]
            except (IndexError, ValueError):
                url_phone = ""
        # Try the modern header data attribute, then a couple of legacy
        # selectors; return whichever is non-empty.
        for selector in (
            'header [data-testid="conversation-info-header-chat-title"]',
            'header [data-testid="chat-title"]',
            'header [title]',
        ):
            try:
                el = await self.page.query_selector(selector)
                if el:
                    text = (await el.get_attribute("title")) or (await el.inner_text())
                    digits = "".join(c for c in text if c.isdigit() or c == "+")
                    if digits and 7 <= len(digits.replace("+", "")) <= 15:
                        return digits
            except Exception:
                continue
        return url_phone or None

    async def get_new_messages(self) -> List[str]:
        messages = []
        try:
            chat_elements = await self.page.query_selector_all('.copyable-text.selectable-text')
            for elem in chat_elements[-10:]:
                text = await elem.text_content()
                if text:
                    messages.append(sanitize_string(text, 500))
        except Exception:
            pass
        return messages

    async def _classify_incoming(self, message: str) -> str:
        prompt = f"""Classify this WhatsApp message as exactly one word: interested, question, not_interested, stop.

Message: "{message}"

Respond with only the classification."""
        # Whitelist is unified across email and WhatsApp classifiers.
        valid = {"interested", "question", "not_interested", "stop"}
        if self.ai:
            try:
                result = await self.ai.generate(prompt, "You are a message classifier.")
                classification = result.strip().lower().split()[0]
                if classification in valid:
                    return classification
            except Exception as exc:
                # Don't echo the prospect's message body in the log line.
                # See review S5.
                logger.error("WhatsApp classification failed: %s", type(exc).__name__)
        # Conservative fallback: do not auto-reply when AI is unavailable.
        # Changed from "question" (which triggered AI auto-replies to STOP
        # messages) to "neutral" (no action taken). See code review B4 fix.
        return "neutral"

    async def _generate_answer(self, question: str, lead: dict) -> str:
        if self.ai:
            prompt = f"""Answer this prospect question briefly and helpfully:

Question: "{question}"

Keep under 100 words."""
            try:
                return sanitize_string(await self.ai.generate(prompt, "You are a helpful sales rep."), 500)
            except Exception as exc:
                # Don't echo the prospect's question in the log line.
                logger.error("AI answer generation failed: %s", type(exc).__name__)
        return "Thanks for your message! I'll follow up soon."

    async def _get_lead_id_by_phone(self, phone: str) -> Optional[int]:
        cursor = await self.db.db.execute(
            "SELECT id FROM leads WHERE phone = ? LIMIT 1", (phone,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def _store_whatsapp_response(self, lead_id, phone, body, classification):
        await self.db.db.execute(
            "INSERT INTO whatsapp_responses (lead_id, phone, body, classification) VALUES (?, ?, ?, ?)",
            (lead_id, phone, body, classification)
        )
        await self.db.db.commit()

    async def close(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()