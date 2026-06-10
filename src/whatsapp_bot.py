import asyncio
import logging
import os
from pathlib import Path
from typing import Optional, List

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)


class WhatsAppBot:
    def __init__(self, data_dir: str = "data/whatsapp"):
        self.data_dir = Path(__file__).parent.parent / data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.playwright = None
        self.browser = None
        self.page = None
        self.db = None
        self.ai = None
        self.calendly_link = os.getenv("CALENDLY_LINK", "")

    async def start(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.data_dir),
            headless=False,
        )
        self.page = await self.browser.new_page()
        await self.page.goto("https://web.whatsapp.com")
        await self._wait_for_login()

    async def _wait_for_login(self):
        try:
            await self.page.wait_for_selector('[aria-label="Chat list"]', timeout=60000)
            logger.info("WhatsApp Web logged in")
        except Exception:
            logger.warning("Please scan QR code to log in")
            await asyncio.to_thread(input, "Press Enter after scanning QR code...")

    def _format_phone(self, phone: str) -> str:
        """Format phone number for WhatsApp (remove +, add country code if missing)."""
        phone = phone.replace("+", "").replace("-", "").replace(" ", "")
        if not phone.startswith("1") and len(phone) == 10:
            phone = "1" + phone  # Add US country code
        return phone

    async def send_message(self, phone: str, message: str) -> bool:
        try:
            phone = self._format_phone(phone)
            url = f"https://web.whatsapp.com/send?phone={phone}"
            await self.page.goto(url)
            
            await self.page.wait_for_selector('[aria-label="Type a message"]', timeout=15000)
            await self.page.fill('[aria-label="Type a message"]', message)
            await self.page.keyboard.press("Enter")
            
            await asyncio.sleep(1)  # Wait for send
            logger.info(f"Message sent to {phone}")
            return True
        except Exception as exc:
            logger.error(f"Failed to send WhatsApp to {phone}: {exc}")
            return False

    async def get_new_messages(self) -> List[str]:
        messages = []
        try:
            chat_elements = await self.page.query_selector_all('.copyable-text.selectable-text')
            for elem in chat_elements[-10:]:
                text = await elem.text_content()
                if text:
                    messages.append(text.strip())
        except Exception:
            pass
        return messages

    async def poll_new_messages(self):
        """Poll for unread WhatsApp messages and process them."""
        if not self.page or not self.db:
            logger.warning("WhatsApp not connected or DB not set")
            return 0

        processed = 0
        try:
            # Get unread chats
            chat_elements = await self.page.query_selector_all('[role="textbox"][data-tab="10"]')
            for elem in chat_elements:
                # Click to open chat
                await elem.click()
                await asyncio.sleep(1)
                
                # Get latest message
                messages = await self.get_new_messages()
                if not messages:
                    continue
                
                latest_msg = messages[-1]
                
                # Extract phone from URL
                current_url = self.page.url
                phone = current_url.split("phone=")[1].split("&")[0] if "phone=" in current_url else ""
                
                # Get lead_id from phone
                lead_id = await self._get_lead_id_by_phone(phone)
                
                # Classify with AI
                classification = await self._classify_incoming(latest_msg)
                
                # Store in DB
                await self._store_whatsapp_response(lead_id, phone, latest_msg, classification)
                
                # Handle based on classification
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

    async def _poll_loop(self, interval: int = 300):
        """Continuous polling loop with 5-minute interval."""
        while True:
            await self.poll_new_messages()
            await asyncio.sleep(interval)

    async def _classify_incoming(self, message: str) -> str:
        prompt = f"""Classify this WhatsApp message as exactly one word: interested, question, not_interested, stop.

Message: "{message}"

Respond with only the classification."""
        if self.ai:
            result = await self.ai.generate(prompt, "You are a message classifier.")
            return result.strip().lower().split()[0]
        return "question"

    async def _generate_answer(self, question: str, lead: dict) -> str:
        if self.ai:
            prompt = f"""Answer this prospect question briefly and helpfully.

Question: "{question}"

Keep under 100 words."""
            return await self.ai.generate(prompt, "You are a helpful sales rep.")
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
        await self.db.commit()

    async def close(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()