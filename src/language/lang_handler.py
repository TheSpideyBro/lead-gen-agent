"""Automatic language detection + translation for global outreach.

GLOBAL-specific: a lead in Berlin should hear from us in German, a lead in São
Paulo in Portuguese. We map the lead's country to its primary business language
and (in "auto"/"native" mode) translate the message with the existing AI client
— no new translation API needed.

OUTREACH_LANGUAGE:
  english -> always English (no translation)
  auto    -> detect from country and translate when non-English (default)
  native  -> same as auto (translate to the local language)
"""
import logging
import os
from typing import Optional, Tuple

try:
    import pycountry
except ImportError:  # pragma: no cover
    pycountry = None

logger = logging.getLogger(__name__)

DEFAULT_LANGUAGE = "English"

# Country (ISO alpha-2) -> primary business language.
COUNTRY_LANGUAGE = {
    "ES": "Spanish", "MX": "Spanish", "AR": "Spanish", "CO": "Spanish", "CL": "Spanish",
    "BR": "Portuguese",
    "DE": "German", "AT": "German", "CH": "German",
    "FR": "French", "BE": "French",
    "IN": "English", "BD": "English", "PK": "English", "US": "English",
    "GB": "English", "UK": "English", "AU": "English", "CA": "English", "SG": "English",
    "AE": "Arabic", "SA": "Arabic",
}


class LangHandler:
    def __init__(self, ai_client=None):
        self.ai = ai_client
        self.mode = os.getenv("OUTREACH_LANGUAGE", "auto").lower()

    def _country_code(self, country: Optional[str]) -> Optional[str]:
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

    def language_for_country(self, country: Optional[str]) -> str:
        code = self._country_code(country)
        return COUNTRY_LANGUAGE.get(code, DEFAULT_LANGUAGE) if code else DEFAULT_LANGUAGE

    async def translate_message(self, text: str, target_language: str) -> str:
        """Translate `text` to `target_language` using the AI client."""
        if not text or not self.ai or target_language == DEFAULT_LANGUAGE:
            return text
        prompt = (f"Translate the following message into {target_language}. "
                  f"Keep the tone natural and professional, preserve any links and "
                  f"placeholders, and return ONLY the translation with no notes:\n\n{text}")
        try:
            return (await self.ai.generate(prompt, "You are a professional translator.")).strip()
        except Exception as exc:
            logger.warning("Translation to %s failed (%s) — sending English", target_language, exc)
            return text

    async def localize(self, text: str, country: Optional[str]) -> Tuple[str, str]:
        """Return (possibly-translated text, language used) for a lead's country."""
        if self.mode == "english":
            return text, DEFAULT_LANGUAGE

        target = self.language_for_country(country)
        if target == DEFAULT_LANGUAGE:
            return text, DEFAULT_LANGUAGE
        translated = await self.translate_message(text, target)
        return translated, target
