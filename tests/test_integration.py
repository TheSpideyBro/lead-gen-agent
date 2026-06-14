"""Integration tests: full schema + migration + a couple of real modules.

Catches the regression where the GLOBAL migration is forgotten (region / icp_tier
columns missing) and where any of the post-merge modules stops loading.
Stdlib-only so it runs in CI without extra deps.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


class TestSchemaAndMigration(unittest.TestCase):
    """LeadDatabase + migrate() must produce a usable schema end-to-end."""

    def setUp(self):
        # Isolate the DB to a temp file so the test is hermetic.
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test.db"
        os.environ["LEAD_DB_PATH"] = str(self.db_path)

    def tearDown(self):
        self._tmpdir.cleanup()
        # Restore any prior env var.
        os.environ.pop("LEAD_DB_PATH", None)

    def test_database_create_then_migrate_round_trip(self):
        async def go():
            # Import inside the coroutine so env is read at the right time.
            from src.database import LeadDatabase
            from src.db.migrate import migrate

            db = LeadDatabase()
            await db.connect()
            # 1) Fresh DB has the base schema (leads, sequences, etc.).
            cur = await db.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='leads'")
            self.assertIsNotNone(await cur.fetchone(), "leads table missing")

            # 2) Run the migration and confirm the new columns are present.
            await migrate(str(self.db_path))
            cur = await db.db.execute("PRAGMA table_info(leads)")
            cols = {row[1] for row in await cur.fetchall()}
            for col in ("icp_score", "icp_tier", "detected_timezone",
                        "detected_language", "region", "funding_stage"):
                self.assertIn(col, cols, f"GLOBAL column {col} missing after migrate()")

            # 3) Insert a lead + enrich + read back.
            lead_id = await db.add_lead({
                "company_name": "Acme", "contact_name": "Jane",
                "email": "jane@acme.test", "phone": "+15555550100",
                "industry": "SaaS", "location": "United States",
            })
            await db.update_lead_global(
                lead_id, icp_score=82, icp_tier="Tier 1",
                detected_timezone="America/New_York",
                detected_language="English", region="north_america",
                funding_stage="series a",
            )
            row = await db.get_lead_by_id(lead_id)
            self.assertEqual(row.get("icp_tier"), "Tier 1")
            self.assertEqual(row.get("region"), "north_america")

            # 4) Migration is idempotent (running again changes nothing).
            added_second_time = await migrate(str(self.db_path))
            self.assertEqual(added_second_time, [],
                             f"Second migrate() should be a no-op, added {added_second_time}")

            await db.close()

        asyncio.run(go())


class TestICPScorerLogic(unittest.TestCase):
    """ICPScorer: title / funding / employees / signals are additive and capped."""

    def test_high_intent_signal_jumps_score(self):
        from src.scoring.icp_scorer import ICPScorer
        scorer = ICPScorer()
        # Use a lead small enough to not hit the 100 cap, so the +25 signal
        # is fully observable.
        base = asyncio.run(scorer.score_lead(
            {"contact_title": "Manager", "employees": 5, "funding_stage": "Pre-seed"},
            detect_tech=False,
        ))
        boosted = asyncio.run(scorer.score_lead(
            {"contact_title": "Manager", "employees": 5, "funding_stage": "Pre-seed",
             "signals": {"high_intent": True}},
            detect_tech=False,
        ))
        self.assertEqual(boosted - base, 25,
                         f"high_intent signal should add 25, got {boosted - base}")

    def test_score_is_capped_at_100(self):
        from src.scoring.icp_scorer import ICPScorer
        scorer = ICPScorer()
        score = asyncio.run(scorer.score_lead(
            {"contact_title": "Founder", "employees": 50, "funding_stage": "Series B",
             "linkedin_url": "https://linkedin.com/in/x", "email": "founder@x.test",
             "signals": {"high_intent": True}},
            detect_tech=False,
        ))
        self.assertLessEqual(score, 100)

    def test_tier_thresholds(self):
        from src.scoring.icp_scorer import ICPScorer
        self.assertEqual(ICPScorer.get_icp_tier(80), "Tier 1")
        self.assertEqual(ICPScorer.get_icp_tier(50), "Tier 2")
        self.assertEqual(ICPScorer.get_icp_tier(20), "Tier 3")
        self.assertTrue(ICPScorer.should_auto_contact("Tier 1"))
        self.assertTrue(ICPScorer.should_auto_contact("Tier 2"))
        self.assertFalse(ICPScorer.should_auto_contact("Tier 3"))


class TestCompliance(unittest.TestCase):
    """ComplianceHandler: footer, opt-out detection, suppression list."""

    def test_footer_omitted_if_already_present(self):
        from src.compliance.compliance_handler import ComplianceHandler
        h = ComplianceHandler(db=None)
        body_with = "Thanks!\n\nunsubscribe link here"
        body_without = "Thanks!"
        self.assertEqual(h.ensure_email_compliant(body_with, "US"), body_with)
        self.assertIn("Reply STOP", h.ensure_email_compliant(body_without, "US"))

    def test_optout_detection(self):
        from src.compliance.compliance_handler import ComplianceHandler
        self.assertTrue(ComplianceHandler.is_optout("please stop contacting me"))
        self.assertTrue(ComplianceHandler.is_optout("Unsubscribe"))
        self.assertTrue(ComplianceHandler.is_optout("remove me"))
        self.assertFalse(ComplianceHandler.is_optout("thanks, looking forward to it"))
        self.assertFalse(ComplianceHandler.is_optout(""))


class TestProxyParser(unittest.TestCase):
    """ProxyManager: parse both `ip:port` and `ip:port:user:pass` formats."""

    def test_parse_ip_port_only(self):
        from src.utils.proxy_manager import ProxyManager
        m = ProxyManager(proxy_list_env="___UNSET___")
        # Inject directly to avoid env coupling.
        m.proxies = m._parse("1.2.3.4:8080")
        self.assertEqual(m.proxies, ["http://1.2.3.4:8080"])

    def test_parse_ip_port_user_pass(self):
        from src.utils.proxy_manager import ProxyManager
        m = ProxyManager(proxy_list_env="___UNSET___")
        m.proxies = m._parse("1.2.3.4:8080:alice:secret")
        self.assertEqual(m.proxies, ["http://alice:secret@1.2.3.4:8080"])

    def test_round_robin_and_masking(self):
        from src.utils.proxy_manager import ProxyManager
        m = ProxyManager(proxy_list_env="___UNSET___")
        m.proxies = m._parse("1.1.1.1:80:u:p")
        # Reset the stats dict to match the proxies we just parsed.
        m.stats = {p: {"success": 0, "fail": 0} for p in m.proxies}
        self.assertEqual(m.next_proxy(), "http://u:p@1.1.1.1:80")
        self.assertEqual(m.next_proxy(), "http://u:p@1.1.1.1:80")  # 1-item pool
        perf = m.performance()
        # Credential must be masked in the report.
        self.assertIn("1.1.1.1:80", perf)
        self.assertNotIn("u:p", str(perf))


if __name__ == "__main__":
    unittest.main()
