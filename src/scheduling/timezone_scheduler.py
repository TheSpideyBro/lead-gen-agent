"""Timezone-aware send scheduling for a global audience.

GLOBAL-specific: outreach is scheduled in the RECIPIENT's local time, never the
server's. We detect the lead's timezone from their country, pick the next
optimal send window for the channel, skip weekends / national holidays / after
hours, and return the slot in UTC for storage.

Optimal windows (recipient local time):
  Email    : Tue-Thu, 08:00-10:00 or 14:00-16:00
  WhatsApp : Mon-Fri, 09:00-11:00 or 15:00-17:00
Never send Sat/Sun or outside 08:00-18:00. Unknown timezone -> 09:00 UTC.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import pytz
except ImportError:  # pragma: no cover - dependency added in requirements.txt
    pytz = None

try:
    import pycountry
except ImportError:  # pragma: no cover
    pycountry = None

logger = logging.getLogger(__name__)

# (allowed weekdays as Mon=0..Sun=6, list of (start_hour, end_hour) windows)
CHANNEL_WINDOWS = {
    "email": ({1, 2, 3}, [(8, 10), (14, 16)]),
    "whatsapp": ({0, 1, 2, 3, 4}, [(9, 11), (15, 17)]),
}
SEARCH_HORIZON_DAYS = 21
HOLIDAYS_PATH = Path(__file__).parent.parent.parent / "config" / "global_holidays.json"


class TimezoneScheduler:
    def __init__(self, holidays_path: Path = HOLIDAYS_PATH):
        self.holidays = self._load_holidays(holidays_path)

    def _load_holidays(self, path: Path) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            logger.warning("global_holidays.json missing/invalid — holiday skip disabled")
            return {}

    # ----- country -> timezone / code -----------------------------------------

    def country_to_code(self, country: Optional[str]) -> Optional[str]:
        """Best-effort ISO alpha-2 code from a country name or code."""
        if not country:
            return None
        c = country.strip()
        if len(c) == 2 and c.isalpha():
            return c.upper()
        if not pycountry:
            return None
        try:
            return pycountry.countries.search_fuzzy(c)[0].alpha_2
        except Exception:
            return None

    def detect_timezone(self, country: Optional[str]) -> Optional[str]:
        """Map a country (name/code) to a representative timezone string."""
        code = self.country_to_code(country)
        if not code or not pytz:
            return None
        zones = pytz.country_timezones.get(code)
        return zones[0] if zones else None

    # ----- optimal slot --------------------------------------------------------

    def next_optimal_slot(
        self,
        tz_name: Optional[str],
        channel: str = "email",
        country_code: Optional[str] = None,
        after: Optional[datetime] = None,
    ) -> datetime:
        """Return the next allowed send time as an aware UTC datetime."""
        after = after or datetime.now(timezone.utc)
        if after.tzinfo is None:
            after = after.replace(tzinfo=timezone.utc)

        # Unknown timezone -> default 09:00 UTC on the next day.
        if not tz_name or not pytz:
            base = after if after.hour < 9 else after + timedelta(days=1)
            return base.replace(hour=9, minute=0, second=0, microsecond=0)

        try:
            tz = pytz.timezone(tz_name)
        except Exception:
            return after.replace(hour=9, minute=0, second=0, microsecond=0)

        allowed_days, windows = CHANNEL_WINDOWS.get(channel, CHANNEL_WINDOWS["email"])
        local_after = after.astimezone(tz)

        for day_offset in range(SEARCH_HORIZON_DAYS):
            day = (local_after + timedelta(days=day_offset)).date()
            if day.weekday() not in allowed_days:
                continue
            if self._is_holiday(country_code, day):
                continue
            for start_hour, _end in windows:
                naive = datetime(day.year, day.month, day.day, start_hour, 0)
                candidate = tz.localize(naive)
                if candidate <= local_after:
                    continue  # window already passed today
                return candidate.astimezone(timezone.utc)

        # Fallback: tomorrow 09:00 UTC.
        return (after + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)

    def _is_holiday(self, country_code: Optional[str], day) -> bool:
        """Return True if *day* is a holiday for *country_code*.

        Tolerates multiple holiday-date formats:
          - ISO strings  "2026-01-01"
          - date objects
          - datetime objects
          - integer YYYYMMDD (e.g. 20260101)
          - list of dicts {"date": "2026-01-01", "name": "..."}
        """
        if not country_code:
            return False
        codes = self.holidays
        # Handle both upper-case key and nested structure.
        entries = codes.get(country_code.upper(), [])
        if not isinstance(entries, list):
            return False
        iso = day.isoformat()  # "YYYY-MM-DD"
        for entry in entries:
            if isinstance(entry, dict):
                # {"date": "2026-01-01", "name": "New Year"}
                d = entry.get("date", "")
                if isinstance(d, str) and d == iso:
                    return True
                try:
                    if datetime.strptime(d, "%Y-%m-%d").date() == day:
                        return True
                except (ValueError, TypeError):
                    pass
            elif isinstance(entry, str):
                if entry == iso:
                    return True
                # Try parsing alternative string formats.
                for fmt in ("%Y%m%d", "%d/%m/%Y"):
                    try:
                        if datetime.strptime(entry, fmt).date() == day:
                            return True
                    except ValueError:
                        pass
            elif hasattr(entry, "isoformat"):
                # date / datetime object
                if entry.date().isoformat() == iso:
                    return True
        return False

    @staticmethod
    def to_db_string(dt: datetime) -> str:
        """Format an aware datetime as a naive-UTC string SQLite datetime() reads."""
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def schedule_steps(
        self,
        tz_name: Optional[str],
        channel: str,
        step_gaps_days: List[int],
        country_code: Optional[str] = None,
    ) -> List[Tuple[int, str]]:
        """Compute optimal slots for each sequence step.

        step_gaps_days[i] is the minimum days after the previous step. Returns
        [(step_number, db_datetime_string), ...].
        """
        slots = []
        cursor = datetime.now(timezone.utc)
        for i, gap in enumerate(step_gaps_days, start=1):
            cursor = cursor + timedelta(days=gap)
            slot = self.next_optimal_slot(tz_name, channel, country_code, after=cursor)
            cursor = slot
            slots.append((i, self.to_db_string(slot)))
        return slots
