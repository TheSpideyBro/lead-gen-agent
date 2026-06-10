import asyncio
import logging
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)


class WhatsAppBot:
    def __init__(self, data_dir: str = "data/whatsapp"):
        self.data_dir = Path(__file__).parent.parent / data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.playwright = None
        self.browser = None
        self.page = None

    async def start(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.data_dir),
            headless=False,
            args=["--no-sandbox"]
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
            input("Press Enter after scanning QR code...")

    async def send_message(self, phone: str, message: str) -> bool:
        try:
            url = f"https://web.whatsapp.com/send?phone={phone}"
            await self.page.goto(url)
            
            await self.page.wait_for_selector('[aria-label="Type a message"]', timeout=10000)
            await self.page.fill('[aria-label="Type a message"]', message)
            await self.page.keyboard.press("Enter")
            
            logger.info(f"Message sent to {phone}")
            return True
        except Exception as exc:
            logger.error(f"Failed to send WhatsApp to {phone}: {exc}")
            return False

    async def get_new_messages(self) -> list:
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

    async def close(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()