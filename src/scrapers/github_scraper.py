"""GitHub repo-owner scraper (global lead source).

GLOBAL-specific: technical founders worldwide publish their startups on GitHub.
We search repos by topic + stars (traction signal) and resolve each repo owner
to a lead. Uses the official GitHub REST API — genuinely free: 60 requests/hour
unauthenticated, 5000/hour with a GITHUB_TOKEN.
"""
import logging
import os
from typing import List

import aiohttp

from src.scrapers.prospect_scraper import Lead
from src.utils.api_usage import APIUsageTracker

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.github.com/search/repositories"
USER_URL = "https://api.github.com/users/{login}"
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)
DEFAULT_TOPICS = ["saas", "startup", "b2b"]


class GitHubScraper:
    def __init__(self):
        self.token = os.getenv("GITHUB_TOKEN", "")
        self.usage = APIUsageTracker()
        # Pick the quota bucket that matches our auth level.
        self.source = "github_authed" if self.token else "github_anon"

    def _headers(self) -> dict:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "lead-gen-agent"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def search_prospects(
        self,
        topics: List[str] = None,
        min_stars: int = 50,
        max_results: int = 20,
    ) -> List[Lead]:
        topics = topics or DEFAULT_TOPICS
        query = " ".join(f"topic:{t}" for t in topics) + f" stars:>={min_stars}"
        params = {"q": query, "sort": "stars", "order": "desc",
                  "per_page": min(max_results, 50)}

        if not self.usage.can_spend(self.source):
            logger.warning("GitHub: quota for %s reached — skipping", self.source)
            return []

        try:
            async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
                async with session.get(SEARCH_URL, params=params,
                                       headers=self._headers()) as resp:
                    self.usage.record(self.source)
                    if resp.status != 200:
                        logger.warning("GitHub search HTTP %s — %s", resp.status,
                                       (await resp.text())[:200])
                        return []
                    items = (await resp.json()).get("items", [])

                leads = []
                for repo in items:
                    lead = await self._owner_to_lead(session, repo)
                    if lead:
                        leads.append(lead)
                return leads
        except Exception as exc:
            logger.error("GitHub request failed: %s", exc)
            return []

    async def _owner_to_lead(self, session: aiohttp.ClientSession, repo: dict):
        owner = repo.get("owner") or {}
        login = owner.get("login")
        if not login:
            return None

        # Hydrate the owner profile for email/company/location/blog when quota allows.
        profile = {}
        if self.usage.can_spend(self.source):
            try:
                async with session.get(USER_URL.format(login=login),
                                       headers=self._headers()) as resp:
                    self.usage.record(self.source)
                    if resp.status == 200:
                        profile = await resp.json()
            except Exception:
                profile = {}

        website = profile.get("blog") or repo.get("homepage")
        if website and not website.startswith("http"):
            website = f"https://{website}"

        return Lead(
            company_name=profile.get("company") or repo.get("name") or login,
            contact_name=profile.get("name") or login,
            contact_title="Founder / Maintainer",
            email=profile.get("email"),  # only present if the user made it public
            phone=None,
            website=website,
            industry="Software",
            location=profile.get("location"),
            employees=None,
            source="github",
            country=profile.get("location"),
            linkedin_url=None,
            signals={"stars": repo.get("stargazers_count", 0)},
        )
