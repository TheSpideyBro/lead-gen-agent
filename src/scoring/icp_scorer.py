"""Ideal Customer Profile (ICP) scoring — 0..100 firmographic fit score.

GLOBAL-specific: replaces location-weighted scoring with firmographic fit that
works for any country. A lead's tier (1/2/3) decides whether we auto-contact:
only Tier 1 and Tier 2 are contacted automatically.
"""
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=15)

# Title buckets (case-insensitive substring match).
TITLE_TOP = ("ceo", "founder", "co-founder", "cofounder", "owner", "president")
TITLE_MID = ("cmo", "vp", "vice president", "head of", "director", "chief")
TITLE_LOW = ("manager", "lead", "growth")

# Funding-stage points.
FUNDING_POINTS = {"series a": 25, "series b": 25, "series c": 25,
                  "seed": 20, "bootstrapped": 15, "pre-seed": 15}

# Generic mailbox prefixes (lower email-quality signal).
GENERIC_PREFIXES = {"info", "contact", "hello", "hi", "support", "sales",
                    "admin", "team", "office", "mail", "enquiries", "inquiries"}

# Tech-stack signatures detectable from response headers / HTML.
TECH_SIGNATURES = {
    "Shopify": ("shopify",),
    "WordPress": ("wp-content", "wordpress"),
    "Webflow": ("webflow",),
}


class ICPScorer:
    async def score_lead(self, lead: dict, detect_tech: bool = True) -> int:
        """Return a 0..100 ICP score. Accepts a lead dict (DB row or scraped)."""
        score = 0
        score += self._title_points(lead.get("contact_title"))
        score += self._funding_points(lead.get("funding_stage"))
        score += self._employee_points(lead.get("employees"))

        if detect_tech and lead.get("website"):
            if await self._detect_tech_stack(lead["website"]):
                score += 10

        # Social proof: a LinkedIn presence.
        if lead.get("linkedin_url"):
            score += 5

        # Email quality: personal mailbox beats a generic one.
        score += self._email_points(lead.get("email"))

        # Intent boost: ProductHunt high-upvote launchers (Section 1 signal).
        signals = lead.get("signals") or {}
        if isinstance(signals, dict) and signals.get("high_intent"):
            score += 25

        return min(100, score)

    def _title_points(self, title: Optional[str]) -> int:
        if not title:
            return 0
        t = title.lower()
        if any(k in t for k in TITLE_TOP):
            return 30
        if any(k in t for k in TITLE_MID):
            return 20
        if any(k in t for k in TITLE_LOW):
            return 10
        return 0

    def _funding_points(self, stage: Optional[str]) -> int:
        if not stage:
            return 0
        return FUNDING_POINTS.get(stage.strip().lower(), 0)

    def _employee_points(self, employees) -> int:
        try:
            n = int(employees)
        except (TypeError, ValueError):
            return 0
        if 10 <= n <= 100:
            return 25
        if 100 < n <= 500:
            return 15
        return 5  # <10 or >500

    def _email_points(self, email: Optional[str]) -> int:
        if not email or "@" not in email:
            return 0
        local = email.split("@", 1)[0].lower()
        return 0 if local in GENERIC_PREFIXES else 5

    async def _detect_tech_stack(self, website: str) -> Optional[str]:
        """Lightweight Wappalyzer-style check: look for vendor fingerprints in
        the response headers and the first chunk of HTML."""
        if not website.startswith("http"):
            website = f"https://{website}"
        try:
            async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
                async with session.get(website) as resp:
                    headers = " ".join(f"{k}:{v}" for k, v in resp.headers.items()).lower()
                    html = (await resp.text())[:50000].lower()
        except Exception:
            return None

        blob = headers + " " + html
        for tech, sigs in TECH_SIGNATURES.items():
            if any(sig in blob for sig in sigs):
                return tech
        return None

    @staticmethod
    def get_icp_tier(score: int) -> str:
        if score >= 75:
            return "Tier 1"
        if score >= 50:
            return "Tier 2"
        return "Tier 3"

    @staticmethod
    def should_auto_contact(tier: str) -> bool:
        """Only Tier 1 and Tier 2 leads are contacted automatically."""
        return tier in ("Tier 1", "Tier 2")
