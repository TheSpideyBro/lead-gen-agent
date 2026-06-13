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
        phone = sanitize_string(phone).replace("+", "").replace("-", "").replace(" ", "")
        if not phone.startswith("1") and len(phone) == 10:
            phone = "1" + phone
        return phone

    async def send_message(self, phone: str, message: str) -> bool:
        if not validate_phone(phone):
            logger.warning(f"Invalid phone number: {phone}")
            return False

        try:
            phone = self._format_phone(phone)
            url = f"https://web.whatsapp.com/send?phone={phone}"
            await self.page.goto(url, timeout=30000)
            
            await self.page.wait_for_selector(self.SELECTORS["message_input"], timeout=15000)
            await self.page.fill(self.SELECTORS["message_input"], sanitize_string(message, 1000))
            await self.page.keyboard.press("Enter")
            
            await asyncio.sleep(1)
            logger.info(f"Message sent to {phone}")
            return True
        except Exception as exc:
            logger.error(f"Failed to send WhatsApp to {phone}: {exc}")
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
                current_url = self.page.url
                phone = current_url.split("phone=")[1].split("&")[0] if "phone=" in current_url else ""
                
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
                    
                elif classification == "stop":
                    if lead_id:
                        await self.db.update_lead_status(lead_id, "unsubscribed")
                        await self.db.stop_all_sequences(lead_id)
                    processed += 1

        except Exception as exc:
            logger.error(f"Polling error: {exc}")
            
        return processed

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
        if self.ai:
            try:
                result = await self.ai.generate(prompt, "You are a message classifier.")
                classification = result.strip().lower().split()[0]
                valid = {"interested", "question", "not_interested", "stop"}
                return classification if classification in valid else "question"
            except Exception as e:
                logger.error(f"Classification failed: {e}")
        return "question"

    async def _generate_answer(self, question: str, lead: dict) -> str:
        if self.ai:
            prompt = f"""Answer this prospect question briefly and helpfully:

Question: "{question}"

Keep under 100 words."""
            try:
                return sanitize_string(await self.ai.generate(prompt, "You are a helpful sales rep."), 500)
            except Exception as e:
                logger.error(f"AI answer generation failed: {e}")
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