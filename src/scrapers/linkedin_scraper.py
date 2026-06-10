import asyncio
import logging
import os
import random
from pathlib import Path
from typing import Optional, List
from urllib.parse import quote_plus

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)


class LinkedInScraper:
    def __init__(self, data_dir: str = "data/linkedin"):
        self.data_dir = Path(__file__).parent.parent / data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.playwright = None
        self.browser = None
        self.page = None
        self.email = os.getenv("LINKEDIN_EMAIL", "")
        self.password = os.getenv("LINKEDIN_PASSWORD", "")

    async def start(self):
        """Launch browser with persistent session."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.data_dir),
            headless=False,
        )
        self.page = await self.browser.new_page()
        await self._login_if_needed()

    async def _login_if_needed(self):
        """Check if logged in, otherwise prompt for manual login."""
        await self.page.goto("https://www.linkedin.com")
        try:
            await self.page.wait_for_selector('.global-nav__me img', timeout=10000)
            logger.info("LinkedIn session already active")
        except Exception:
            if self.email and self.password:
                await self._auto_login()
            else:
                logger.warning("Please log in manually - session will persist")
                await asyncio.to_thread(input, "Press Enter after logging in to LinkedIn...")

    async def _auto_login(self):
        """Automated login using credentials from .env."""
        await self.page.fill('input[name="session_key"]', self.email)
        await self.page.fill('input[name="session_password"]', self.password)
        await self.page.click('button[type="submit"]')
        await asyncio.sleep(5)
        logger.info("LinkedIn login attempted")

    async def search_prospects(self, niche: str, location: str, max_results: int = 10) -> List[dict]:
        """Search LinkedIn Sales Navigator for prospects."""
        if not self.page:
            await self.start()

        query = f'{niche} {location} (CEO OR Founder OR "Marketing Manager")'
        search_url = f"https://www.linkedin.com/sales/search/people?query={quote_plus(query)}"
        await self.page.goto(search_url)
        
        await self.page.wait_for_selector('.search-results', timeout=30000)
        
        cards = await self.page.query_selector_all('.search-result')
        leads = []
        
        for i, card in enumerate(cards[:max_results]):
            lead = await self._extract_lead(card)
            if lead:
                leads.append(lead)
            await asyncio.sleep(random.randint(3, 8))  # Rate limit
        
        return leads

    async def _extract_lead(self, card) -> Optional[dict]:
        """Extract lead data from search result card."""
        try:
            name_elem = await card.query_selector('.name')
            name = await name_elem.inner_text() if name_elem else ""
            
            title_elem = await card.query_selector('.title')
            title = await title_elem.inner_text() if title_elem else ""
            
            company_elem = await card.query_selector('.company')
            company = await company_elem.inner_text() if company_elem else ""
            
            website = ""
            if company_elem:
                link_elem = await company_elem.query_selector('a')
                if link_elem:
                    website = await link_elem.get_attribute('href') or ""
            
            location_elem = await card.query_selector('.location')
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