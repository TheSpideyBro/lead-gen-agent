"""Apollo.io people-search scraper (global lead source).

GLOBAL-specific: Apollo indexes companies and people worldwide, so this replaces
location-bound search with firmographic search (industry / employee range /
keywords / titles). Uses the official REST API.

Reality check: Apollo's free tier rate-limits the search endpoint and gates
email reveal behind paid credits — without a funded key, results may omit
emails. This client degrades gracefully (logs a warning, returns []) when no
APOLLO_API_KEY is configured or the daily quota is exhausted.
"""
import logging
import os
from typing import List, Optional

import aiohttp

from src.scrapers.prospect_scraper import Lead
from src.utils.api_usage import APIUsageTracker

logger = logging.getLogger(__name__)

APOLLO_SEARCH_URL = "https://api.apollo.io/v1/mixed_people/search"
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)


class ApolloScraper:
    SOURCE = "apollo"

    def __init__(self):
        self.api_key = os.getenv("APOLLO_API_KEY", "")
        self.usage = APIUsageTracker()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def search_prospects(
        self,
        titles: List[str],
        industries: Optional[List[str]] = None,
        keywords: str = "",
        min_employees: int = 10,
        max_employees: int = 200,
        per_page: int = 25,
    ) -> List[Lead]:
        if not self.is_configured():
            logger.warning("Apollo: APOLLO_API_KEY not set — skipping Apollo source")
            return []
        if not self.usage.can_spend(self.SOURCE):
            logger.warning("Apollo: daily quota (%d) reached — skipping",
                           self.usage.limit_for(self.SOURCE))
            return []

        payload = {
            "api_key": self.api_key,
            "page": 1,
            "per_page": per_page,
            "person_titles": titles,
            "organization_num_employees_ranges": [f"{min_employees},{max_employees}"],
        }
        if keywords:
            payload["q_keywords"] = keywords
        if industries:
            payload["q_organization_industries"] = industries

        try:
            async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
                async with session.post(APOLLO_SEARCH_URL, json=payload) as resp:
                    self.usage.record(self.SOURCE)
                    if resp.status != 200:
                        logger.warning("Apollo: HTTP %s — %s", resp.status,
                                       (await resp.text())[:200])
                        return []
                    data = await resp.json()
        except Exception as exc:
            logger.error("Apollo request failed: %s", exc)
            return []

        return [self._to_lead(p) for p in data.get("people", []) if p]

    def _to_lead(self, person: dict) -> Lead:
        org = person.get("organization") or {}
        name = " ".join(filter(None, [person.get("first_name"), person.get("last_name")])) or None
        country = person.get("country") or org.get("country")
        return Lead(
            company_name=org.get("name") or person.get("organization_name") or "Unknown",
            contact_name=name,
            contact_title=person.get("title"),
            email=person.get("email"),  # may be None on free tier (email not revealed)
            phone=None,
            website=org.get("website_url"),
            industry=org.get("industry"),
            location=", ".join(filter(None, [person.get("city"), country])) or country,
            employees=org.get("estimated_num_employees"),
            source=self.SOURCE,
            country=country,
            linkedin_url=person.get("linkedin_url"),
        )
