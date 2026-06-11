import asyncio
import logging
import os
import random
from pathlib import Path
from typing import Optional, List
from urllib.parse import quote_plus

from playwright.async_api import async_playwright

from src.utils.rate_limiter import AsyncRetry

logger = logging.getLogger(__name__)


class LinkedInScraper:
    SELECTORS = {
        "login_avatar": '.global-nav__me img',
        "email_input": 'input[name="session_key"]',
        "password_input": 'input[name="session_password"]',
        "submit_button": 'button[type="submit"]',
        "search_results": '.search-results, .artdeco-list',
        "result_cards": '.search-result, .linkedin-result-card',
    }

    def __init__(self, data_dir: str = "data/linkedin"):
        self.data_dir = Path(os.getenv("LINKEDIN_DATA_DIR", data_dir))
        self.data_dir = Path(__file__).parent.parent / self.data_dir if not self.data_dir.is_absolute() else self.data_dir
        self.playwright = None
        self.browser = None
        self.page = None
        self.email = os.getenv("LINKEDIN_EMAIL", "")
        self.password = os.getenv("LINKEDIN_PASSWORD", "")
        self.retry = AsyncRetry(max_attempts=3, base_delay=2.0)

    async def start(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.data_dir),
            headless=os.getenv("LINKEDIN_HEADLESS", "false").lower() == "true",
        )
        self.page = await self.browser.new_page()
        await self._login_if_needed()

    async def _login_if_needed(self):
        try:
            await self.page.goto("https://www.linkedin.com", timeout=30000)
            await self.page.wait_for_selector(self.SELECTORS["login_avatar"], timeout=10000)
            logger.info("LinkedIn session already active")
        except Exception:
            if self.email and self.password:
                await self._auto_login()
            else:
                logger.warning("Please log in manually - session will persist")
                await asyncio.to_thread(input, "Press Enter after logging in to LinkedIn...")

    async def _auto_login(self):
        try:
            await self.page.fill(self.SELECTORS["email_input"], self.email)
            await self.page.fill(self.SELECTORS["password_input"], self.password)
            await self.page.click(self.SELECTORS["submit_button"])
            await self.page.wait_for_selector(self.SELECTORS["login_avatar"], timeout=15000)
            logger.info("LinkedIn login successful")
        except Exception as e:
            logger.error(f"LinkedIn login failed: {e}")
            raise

    async def search_prospects(self, niche: str, location: str, max_results: int = 10) -> List[dict]:
        if not self.page:
            await self.start()

        query = f'{niche} {location} (CEO OR Founder OR "Marketing Manager")'
        search_url = f"https://www.linkedin.com/sales/search/people?query={quote_plus(query)}"
        
        try:
            await self.page.goto(search_url, timeout=30000)
            await self.page.wait_for_selector(self.SELECTORS["search_results"], timeout=30000)
        except Exception as e:
            logger.error(f"Failed to load LinkedIn search page: {e}")
            return []

        cards = await self.page.query_selector_all(self.SELECTORS["result_cards"])
        leads = []

        for i, card in enumerate(cards[:max_results]):
            lead = await self._extract_lead(card)
            if lead:
                leads.append(lead)
            await asyncio.sleep(random.randint(3, 8))

        return leads

    async def _extract_lead(self, card) -> Optional[dict]:
        try:
            name_elem = await card.query_selector('.name, .actor-name')
            name = await name_elem.inner_text() if name_elem else ""

            title_elem = await card.query_selector('.title, .text-heading-small')
            title = await title_elem.inner_text() if title_elem else ""

            company_elem = await card.query_selector('.company, .company-link')
            company = await company_elem.inner_text() if company_elem else ""

            website = ""
            if company_elem:
                link_elem = await company_elem.query_selector('a')
                if link_elem:
                    website = await link_elem.get_attribute('href') or ""

            location_elem = await card.query_selector('.location, .text-body-small')
            loc = await location_elem.inner_text() if location_elem else ""

            return {
                "contact_name": name.strip(),
                "contact_title": title.strip(),
                "company_name": company.strip(),
                "website": website.strip(),
                "location": loc.strip(),
            }
        except Exception as e:
            logger.error(f"Extraction error: {e}")
            return None

    async def close(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()