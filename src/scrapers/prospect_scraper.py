import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import quote_plus, unquote
import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)


@dataclass
class Lead:
    company_name: str
    contact_name: Optional[str]
    contact_title: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    website: Optional[str]
    industry: Optional[str]
    location: Optional[str]
    employees: Optional[int]
    source: str


class GoogleSearchScraper:
    def __init__(self):
        self.api_key = os.getenv("GOOGLE_API_KEY", "")
        self.search_id = os.getenv("GOOGLE_SEARCH_ID", "")
        self.use_api = bool(self.api_key and self.search_id)

    async def search_prospects(self, query: str, max_results: int = 20) -> List[Lead]:
        leads: List[Lead] = []
        if self.use_api:
            leads = await self._api_search(query, max_results)
        else:
            leads = await self._free_search(query, max_results)
        return leads[:max_results]

    async def _api_search(self, query: str, max_results: int) -> List[Lead]:
        leads: List[Lead] = []
        url = "https://www.googleapis.com/customsearch/v1"
        async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
            params = {
                "key": self.api_key,
                "cx": self.search_id,
                "q": query,
                "num": min(max_results, 10),
            }
            async with session.get(url, params=params) as resp:
                data = await resp.json()
                for item in data.get("items", []):
                    leads.append(Lead(
                        company_name=self._extract_company_name(item.get("title", "")),
                        contact_name=None,
                        contact_title=None,
                        email=None,
                        phone=None,
                        website=item.get("link"),
                        industry=query.split()[0] if query else None,
                        location=None,
                        employees=None,
                        source="google_api",
                    ))
        return leads

    async def _free_search(self, query: str, max_results: int) -> List[Lead]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
        }
        url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
        leads = []
        
        try:
            async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
                async with session.get(url, headers=headers) as resp:
                    html = await resp.text()
                    soup = BeautifulSoup(html, "html.parser")
                    result_bodies = soup.select(".result__body")
                    logger.info(f"Found {len(result_bodies)} result bodies")
                    
                    for body in result_bodies[:max_results]:
                        link = ""
                        for a in body.select("a"):
                            href = a.get("href", "")
                            if href and "duckduckgo.com/l/?uddg=" in href:
                                decoded = unquote(href.split("uddg=")[1].split("&")[0])
                                if decoded.startswith("http"):
                                    link = decoded
                                    break
                        
                        title_elem = body.select_one(".result__title")
                        title = title_elem.get_text(strip=True) if title_elem else ""
                        
                        if link and title:
                            leads.append(Lead(
                                company_name=self._extract_company_name(title),
                                contact_name=None,
                                contact_title=None,
                                email=None,
                                phone=None,
                                website=link,
                                industry=query.split()[0] if query else None,
                                location=None,
                                employees=None,
                                source="duckduckgo",
                            ))
        except Exception as exc:
            logger.warning(f"DuckDuckGo search failed: {exc}. Try setting GOOGLE_API_KEY for better results.")
        
        return await self._enrich_leads(leads)

    async def _enrich_leads(self, leads: List[Lead]) -> List[Lead]:
        for lead in leads:
            if lead.website and not lead.website.startswith("http"):
                lead.website = f"https://{lead.website}"
        return leads

    def _extract_company_name(self, title: str) -> str:
        if "|" in title:
            return title.split("|")[0].strip()
        if "–" in title:
            return title.split("–")[0].strip()
        return title.split("-")[0].strip() if "-" in title else title


class EmailExtractor:
    async def find_email(self, website: str, company: str) -> Optional[str]:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        try:
            async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
                contact_url = f"{website.rstrip('/')}/contact"
                async with session.get(contact_url, headers=headers) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        soup = BeautifulSoup(html, "html.parser")
                        text = soup.get_text()
                        emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
                        if emails:
                            return emails[0]
        except Exception:
            pass
        return None


class LeadScraper:
    def __init__(self):
        self.google_scraper = GoogleSearchScraper()
        self.email_extractor = EmailExtractor()

    async def find_prospects(self, niches: List[str], locations: List[str]) -> List[Lead]:
        all_leads = []
        
        for niche in niches:
            for location in locations:
                query = f"{niche} companies in {location} digital marketing"
                leads = await self.google_scraper.search_prospects(query, 10)
                if not leads:
                    logger.warning(f"No leads found for '{query}' - DuckDuckGo may be blocking the request")
                for lead in leads:
                    lead.industry = niche
                    lead.location = location
                    if lead.website and not lead.email:
                        lead.email = await self.email_extractor.find_email(lead.website, lead.company_name)
                    all_leads.append(lead)
                await asyncio.sleep(3)
        
        return list({lead.website: lead for lead in all_leads if lead.website}.values())

    async def cleanup_duplicate(self, leads: List[Lead]) -> List[Lead]:
        seen = set()
        unique = []
        for lead in leads:
            key = lead.website or lead.company_name.lower()
            if key not in seen:
                seen.add(key)
                unique.append(lead)
        return unique