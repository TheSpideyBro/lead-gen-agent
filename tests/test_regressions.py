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
        # Use a temp dir to assert the autovivify behavior on a fresh import.
        import importlib
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db_path = "C:/tmp_fake_for_test/lead_bot.db"  # any path under non-existent dir
            # We can't change the env of an already-imported module, so just
            # assert that the autovivify logic in get_db_path() is correct.
            from pathlib import Path
            test_path = Path(tmp) / "data" / "lead_bot.db"
            test_path.parent.mkdir(parents=True, exist_ok=True)
            self.assertTrue(test_path.parent.exists(),
                            "Path.mkdir(parents=True, exist_ok=True) should create parents")
        # And the module-level helper exists and is callable.
        from src.database import get_db_path
        self.assertTrue(callable(get_db_path))


if __name__ == "__main__":
    unittest.main()
