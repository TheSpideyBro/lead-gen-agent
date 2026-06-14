"""Regression tests that guard against the bugs the code review identified.

These are intentionally tiny and dependency-free (stdlib only) so they run in
CI without provisioning a venv full of AI/scraping libraries.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


class TestDailySummaryTableName(unittest.TestCase):
    """B1 \u2014 daily_summary must query the real `sequences` table, not `message_sequences`."""

    def test_no_message_sequences_string(self):
        from src.reports import daily_summary
        src = Path(daily_summary.__file__).read_text(encoding="utf-8")
        self.assertNotIn(
            "message_sequences", src,
            "daily_summary.py must not reference the non-existent 'message_sequences' table",
        )


class TestSignatureSafety(unittest.TestCase):
    """Signature must use str.replace (positional) so a literal '{' in the
    signature does not raise KeyError."""

    def test_signature_uses_replace_not_format(self):
        from src.outreach import email_generator
        from src.outreach.email_generator import MessageGenerator
        # Construct without calling __init__ (no AI client needed for this test).
        mg = MessageGenerator.__new__(MessageGenerator)
        mg.profile = {
            "your_email": "x@example.com",
            "your_phone": "+1",
            "email_signature": "Hi {email} phone {phone} \u2014 JSON: {\"k\": 1}",
        }
        out = mg._signature()
        self.assertIn("x@example.com", out)
        self.assertIn("{\"k\": 1}", out)


class TestPhoneNormalization(unittest.TestCase):
    """B9/S9 \u2014 _format_phone must not silently misroute non-NANP numbers."""

    def test_no_silent_prepend_for_european(self):
        from src.whatsapp_bot import WhatsAppBot
        bot = WhatsAppBot.__new__(WhatsAppBot)  # bypass __init__ (no Playwright)
        # phonenumbers may or may not be installed; both code paths must NOT
        # prefix a 1 to a 10-digit European number.
        try:
            result = bot._format_phone("442071838750")
        except ValueError:
            self.skipTest("phonenumbers library is the only way to parse this number")
        self.assertFalse(
            result.startswith("1442"),
            f"European number was silently rerouted via 1-prefix: {result!r}",
        )


class TestDataDirAutocreate(unittest.TestCase):
    def test_data_dir_created_on_load(self):
        from src import database
        self.assertTrue(database.DB_PATH.parent.exists())


if __name__ == "__main__":
    unittest.main()
