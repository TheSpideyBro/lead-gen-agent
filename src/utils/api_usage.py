"""Per-source API usage tracker with a daily quota reset (midnight UTC).

GLOBAL-specific: every external lead source (Apollo, GitHub, ProductHunt) and
messaging/AI provider has a different free-tier ceiling. We persist counters to
data/api_usage.json so limits survive process restarts, reset them at midnight
UTC, and let callers check remaining quota before spending a request.
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)

# Daily ceilings per source. github has two values depending on auth; the
# scraper picks the right key based on whether a token is configured.
DAILY_LIMITS: Dict[str, int] = {
    "apollo": 50,            # Apollo free tier
    "github_authed": 5000,   # GitHub API with a token (5000/hour, we cap daily)
    "github_anon": 60,       # GitHub API unauthenticated (60/hour)
    "producthunt": 500,      # ProductHunt GraphQL (generous; conservative cap)
    "groq": 14400,           # 30 req/min ~= 43k/day; conservative daily guard
    "d360": 1000,            # 360dialog free tier
}

WARN_THRESHOLD = 0.80  # warn once usage crosses 80% of a limit


def _usage_path() -> Path:
    base = os.getenv("LEAD_DB_PATH", "data/lead_bot.db")
    return Path(base).parent / "api_usage.json"


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class APIUsageTracker:
    """File-backed counter. Cheap synchronous JSON IO — safe to call inline."""

    def __init__(self, path: Path = None):
        self.path = path or _usage_path()
        self._data = self._load()
        self._roll_over_if_new_day()

    def _load(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"date": _today(), "counts": {}}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2)

    def _roll_over_if_new_day(self):
        if self._data.get("date") != _today():
            self._data = {"date": _today(), "counts": {}}
            self._save()

    def limit_for(self, source: str) -> int:
        return DAILY_LIMITS.get(source, 1_000_000)

    def used(self, source: str) -> int:
        self._roll_over_if_new_day()
        return int(self._data["counts"].get(source, 0))

    def remaining(self, source: str) -> int:
        return max(0, self.limit_for(source) - self.used(source))

    def can_spend(self, source: str, n: int = 1) -> bool:
        return self.remaining(source) >= n

    def record(self, source: str, n: int = 1) -> int:
        """Increment a source's counter and return the new total."""
        self._roll_over_if_new_day()
        new_total = self.used(source) + n
        self._data["counts"][source] = new_total
        self._save()

        limit = self.limit_for(source)
        if limit and new_total >= limit * WARN_THRESHOLD:
            pct = int(100 * new_total / limit)
            logger.warning("API usage for '%s' at %d%% (%d/%d today)",
                           source, pct, new_total, limit)
        return new_total

    def snapshot(self) -> Dict[str, dict]:
        """Return {source: {used, limit, remaining}} for every known source."""
        self._roll_over_if_new_day()
        out = {}
        for source in DAILY_LIMITS:
            out[source] = {
                "used": self.used(source),
                "limit": self.limit_for(source),
                "remaining": self.remaining(source),
            }
        return out
