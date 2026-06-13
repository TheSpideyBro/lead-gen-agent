"""ProductHunt launch scraper (global lead source).

GLOBAL-specific: founders launching on ProductHunt are actively building and
very responsive. We pull recent launches and treat high upvote counts as an
intent signal (>=100 upvotes → +25 in the ICP scorer).

Per the "prefer official APIs" decision, this uses ProductHunt's sanctioned
GraphQL API (https://api.producthunt.com/v2/api/graphql) with a developer token
(PRODUCTHUNT_TOKEN) rather than scraping the HTML site (which violates its ToS).
Degrades gracefully when no token is configured.
"""
import logging
import os
from typing import List

import aiohttp

from src.scrapers.prospect_scraper import Lead
from src.utils.api_usage import APIUsageTracker

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://api.producthunt.com/v2/api/graphql"
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)
HIGH_INTENT_UPVOTES = 100

# Recent top launches with their makers and websites.
POSTS_QUERY = """
query RecentPosts($first: Int!) {
  posts(order: VOTES, first: $first) {
    edges {
      node {
        name
        tagline
        votesCount
        website
        makers { name username }
      }
    }
  }
}
"""


class ProductHuntScraper:
    SOURCE = "producthunt"

    def __init__(self):
        self.token = os.getenv("PRODUCTHUNT_TOKEN", "")
        self.usage = APIUsageTracker()

    def is_configured(self) -> bool:
        return bool(self.token)

    async def search_prospects(self, max_results: int = 20) -> List[Lead]:
        if not self.is_configured():
            logger.warning("ProductHunt: PRODUCTHUNT_TOKEN not set — skipping source")
            return []
        if not self.usage.can_spend(self.SOURCE):
            logger.warning("ProductHunt: daily quota reached — skipping")
            return []

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        body = {"query": POSTS_QUERY, "variables": {"first": min(max_results, 50)}}

        try:
            async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
                async with session.post(GRAPHQL_URL, json=body, headers=headers) as resp:
                    self.usage.record(self.SOURCE)
                    if resp.status != 200:
                        logger.warning("ProductHunt HTTP %s — %s", resp.status,
                                       (await resp.text())[:200])
                        return []
                    data = await resp.json()
        except Exception as exc:
            logger.error("ProductHunt request failed: %s", exc)
            return []

        edges = (data.get("data") or {}).get("posts", {}).get("edges", [])
        leads = []
        for edge in edges:
            node = edge.get("node") or {}
            lead = self._to_lead(node)
            if lead:
                leads.append(lead)
        return leads

    def _to_lead(self, node: dict):
        makers = node.get("makers") or []
        maker_name = makers[0]["name"] if makers else None
        upvotes = node.get("votesCount", 0) or 0
        return Lead(
            company_name=node.get("name") or "Unknown",
            contact_name=maker_name,
            contact_title="Founder / Maker",
            email=None,  # resolved later via website by the email extractor
            phone=None,
            website=node.get("website"),
            industry="Tech / Startup",
            location=None,
            employees=None,
            source=self.SOURCE,
            signals={"upvotes": upvotes, "high_intent": upvotes >= HIGH_INTENT_UPVOTES,
                     "tagline": node.get("tagline")},
        )
