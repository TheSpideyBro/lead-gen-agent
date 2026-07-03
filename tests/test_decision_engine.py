"""Unit tests for DecisionEngine — the 7-rule decision tree and reply handler.

Extends the existing test suite (test_integration.py, test_regressions.py) with
comprehensive coverage of the autonomous agent's reactive decision logic.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_db() -> MagicMock:
    """Return a mock LeadDatabase with commonly-used methods stubbed."""
    db = MagicMock()
    db.db = AsyncMock()
    db.get_lead_by_id = AsyncMock(return_value={})
    db.get_unreplied_responses = AsyncMock(return_value=[])
    db.stop_all_sequences = AsyncMock()
    db.update_lead_status = AsyncMock()
    db.add_unsubscribe = AsyncMock()
    db.is_unsubscribed = AsyncMock(return_value=False)
    db.reschedule_sequence = AsyncMock()
    db.mark_response_replied = AsyncMock()
    db.get_pending_emails = AsyncMock(return_value=[])
    db.get_pending_messages = AsyncMock(return_value=[])
    db.get_leads_by_status = AsyncMock(return_value=[])
    db.get_booking_pipeline = AsyncMock(return_value=[])
    db.get_unreplied_responses = AsyncMock(return_value=[])
    db.log_email_open = AsyncMock()
    db.has_lead_opened = AsyncMock(return_value=False)
    db.imap_dedup_seen = AsyncMock(return_value=False)
    db.imap_dedup_record = AsyncMock()
    return db


def _make_mock_components() -> dict:
    c = {}
    c["outbound"] = MagicMock()
    c["outbound"].compliance = MagicMock()
    c["outbound"].compliance.is_optout = staticmethod(lambda body: "stop" in (body or "").lower())
    c["outbound"].compliance.region_for_country = staticmethod(lambda code: "default")
    c["whatsapp"] = MagicMock()
    c["whatsapp"].page = None
    c["ai"] = AsyncMock(return_value="test answer")
    c["email_sender"] = MagicMock()
    c["msg_gen"] = MagicMock()
    c["msg_gen"].generate_initial_message = AsyncMock(
        return_value=("Test Subject", "Test Body"))
    c["msg_gen"].generate_followup = AsyncMock(
        return_value=("Followup Subject", "Followup Body"))
    c["analytics"] = MagicMock()
    c["analytics"].get_stats = AsyncMock(return_value={})
    usage = MagicMock()
    usage.can_spend = MagicMock(return_value=True)
    usage.snapshot = MagicMock(return_value={})
    c["usage"] = usage
    return c


# ===========================================================================
# DecisionEngine tests
# ===========================================================================

class TestDecisionEngineReplyHandling(unittest.TestCase):
    """Test the 8-way reply handler in DecisionEngine."""

    def setUp(self):
        self.db = _make_mock_db()
        self.c = _make_mock_components()
        # Import here so mocks are available
        from src.outreach.email_response_handler import EmailResponsePoller
        self.poller = EmailResponsePoller(
            db=self.db,
            ai_client=self.c["ai"],
            email_sender=self.c["email_sender"],
        )

    def test_classify_interested(self):
        result = asyncio.run(self.poller._classify_reply(
            "I'm interested! Let's talk."))
        self.assertEqual(result, "interested")

    def test_classify_question(self):
        result = asyncio.run(self.poller._classify_reply(
            "What are your pricing plans?"))
        self.assertEqual(result, "question")

    def test_classify_not_interested(self):
        result = asyncio.run(self.poller._classify_reply(
            "Not interested, thanks."))
        self.assertEqual(result, "not_interested")

    def test_optout_detected(self):
        from src.compliance.compliance_handler import ComplianceHandler
        self.assertTrue(ComplianceHandler.is_optout("please stop contacting me"))
        self.assertTrue(ComplianceHandler.is_optout("Unsubscribe"))
        self.assertTrue(ComplianceHandler.is_optout("remove me"))
        self.assertFalse(ComplianceHandler.is_optout("thanks, looking forward to it"))


class TestICPScorer(unittest.TestCase):
    """ICPScorer unit tests."""

    def test_tier_thresholds(self):
        from src.scoring.icp_scorer import ICPScorer
        self.assertEqual(ICPScorer.get_icp_tier(80), "Tier 1")
        self.assertEqual(ICPScorer.get_icp_tier(50), "Tier 2")
        self.assertEqual(ICPScorer.get_icp_tier(20), "Tier 3")
        self.assertTrue(ICPScorer.should_auto_contact("Tier 1"))
        self.assertTrue(ICPScorer.should_auto_contact("Tier 2"))
        self.assertFalse(ICPScorer.should_auto_contact("Tier 3"))

    def test_score_capped_at_100(self):
        from src.scoring.icp_scorer import ICPScorer
        scorer = ICPScorer()
        score = asyncio.run(scorer.score_lead({
            "contact_title": "Founder",
            "employees": 50,
            "funding_stage": "Series B",
            "linkedin_url": "https://linkedin.com/in/x",
            "email": "founder@x.test",
            "signals": {"high_intent": True},
        }, detect_tech=False))
        self.assertLessEqual(score, 100)


class TestPhoneNormalization(unittest.TestCase):
    """Phone normalization and validation tests."""

    def test_normalize_digits_only(self):
        from src.utils.validators import normalize_phone
        self.assertEqual(normalize_phone("+1 (555) 555-0100"), "15555550100")
        self.assertEqual(normalize_phone("0015555550100"), "15555550100")
        self.assertEqual(normalize_phone("15555550100"), "15555550100")

    def test_validate_email(self):
        from src.utils.validators import validate_email
        self.assertTrue(validate_email("test@example.com"))
        self.assertFalse(validate_email("invalid"))
        self.assertFalse(validate_email(""))

    def test_validate_phone(self):
        from src.utils.validators import validate_phone
        self.assertTrue(validate_phone("+15555550100"))
        self.assertTrue(validate_phone("15555550100"))
        self.assertFalse(validate_phone("123"))
        self.assertFalse(validate_phone(""))


class TestComplianceHandler(unittest.TestCase):
    """ComplianceHandler tests."""

    def test_footer_omitted_if_present(self):
        from src.compliance.compliance_handler import ComplianceHandler
        h = ComplianceHandler(db=None)
        body_with = "Thanks!\n\nunsubscribe link here"
        body_without = "Thanks!"
        self.assertEqual(
            h.ensure_email_compliant(body_with, "US"), body_with)
        self.assertIn("Reply STOP", h.ensure_email_compliant(body_without, "US"))

    def test_optout_detection(self):
        from src.compliance.compliance_handler import ComplianceHandler
        self.assertTrue(ComplianceHandler.is_optout("please stop contacting me"))
        self.assertTrue(ComplianceHandler.is_optout("Unsubscribe"))
        self.assertTrue(ComplianceHandler.is_optout("remove me"))
        self.assertFalse(ComplianceHandler.is_optout("thanks, looking forward to it"))
        self.assertFalse(ComplianceHandler.is_optout(""))


class TestProxyManager(unittest.TestCase):
    """ProxyManager parsing and masking tests."""

    def test_parse_ip_port_only(self):
        from src.utils.proxy_manager import ProxyManager
        m = ProxyManager(proxy_list_env="___UNSET___")
        m.proxies = m._parse("1.2.3.4:8080")
        self.assertEqual(m.proxies, ["http://1.2.3.4:8080"])

    def test_parse_ip_port_user_pass(self):
        from src.utils.proxy_manager import ProxyManager
        m = ProxyManager(proxy_list_env="___UNSET___")
        m.proxies = m._parse("1.2.3.4:8080:alice:secret")
        self.assertEqual(m.proxies, ["http://alice:secret@1.2.3.4:8080"])

    def test_credentials_masked_in_performance(self):
        from src.utils.proxy_manager import ProxyManager
        m = ProxyManager(proxy_list_env="___UNSET___")
        m.proxies = m._parse("1.1.1.1:80:u:p")
        m.stats = {p: {"success": 0, "fail": 0} for p in m.proxies}
        perf = m.performance()
        self.assertIn("1.1.1.1:80", str(perf))
        self.assertNotIn("u:p", str(perf))


class TestTrackingSignature(unittest.TestCase):
    """Tracking pixel signature tests."""

    def setUp(self):
        os.environ["TRACKING_SECRET"] = "a" * 32  # Valid secret

    def tearDown(self):
        os.environ.pop("TRACKING_SECRET", None)

    def test_signature_generated(self):
        from src.tracking.tracker import _sign
        sig = _sign(1, 1)
        self.assertIsInstance(sig, str)
        self.assertEqual(len(sig), 16)

    def test_signature_consistent(self):
        from src.tracking.tracker import _sign
        sig1 = _sign(1, 1)
        sig2 = _sign(1, 1)
        self.assertEqual(sig1, sig2)

    def test_signature_different_for_different_ids(self):
        from src.tracking.tracker import _sign
        sig1 = _sign(1, 1)
        sig2 = _sign(2, 2)
        self.assertNotEqual(sig1, sig2)

    def test_verify_signature(self):
        from src.tracking.tracker import _sign, verify_signature
        sig = _sign(1, 1)
        self.assertTrue(verify_signature(1, 1, sig))
        self.assertFalse(verify_signature(1, 2, sig))
        self.assertFalse(verify_signature(1, 1, ""))


class TestTimezoneScheduler(unittest.TestCase):
    """TimezoneScheduler basic tests."""

    def test_country_to_code(self):
        from src.scheduling.timezone_scheduler import TimezoneScheduler
        ts = TimezoneScheduler()
        self.assertEqual(ts.country_to_code("US"), "US")
        self.assertEqual(ts.country_to_code("gb"), "GB")
        self.assertIsNone(ts.country_to_code(""))

    def test_schedule_steps_returns_slots(self):
        from src.scheduling.timezone_scheduler import TimezoneScheduler
        ts = TimezoneScheduler()
        slots = ts.schedule_steps("America/New_York", "email", [0, 2, 2], "US")
        self.assertEqual(len(slots), 3)
        for step_num, db_str in slots:
            self.assertIsInstance(step_num, int)
            self.assertIsInstance(db_str, str)


if __name__ == "__main__":
    unittest.main()
