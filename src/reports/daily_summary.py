# AGENT_OWNER: analytics-001
# TASK_ID: daily-summary-report
import logging
import os
from typing import Dict, Any

logger = logging.getLogger(__name__)


class DailySummary:
    def __init__(self, db, whatsapp_bot=None):
        self.db = db
        self.whatsapp_bot = whatsapp_bot

    async def generate_summary(self) -> Dict[str, Any]:
        today = await self._get_today_date()
        
        new_leads = await self._count_new_leads_today(today)
        emails_sent = await self._count_emails_sent_today(today)
        whatsapp_sent = await self._count_whatsapp_sent_today(today)
        responses = await self._count_responses_today(today)
        hot_leads = await self._count_hot_leads()
        qualified_leads = await self._count_qualified_leads()
        pending_followups = await self._count_pending_followups_today(today)
        
        return {
            "new_leads": new_leads,
            "emails_sent": emails_sent,
            "whatsapp_sent": whatsapp_sent,
            "responses": responses,
            "hot_leads": hot_leads,
            "qualified_leads": qualified_leads,
            "pending_followups": pending_followups,
        }

    async def _get_today_date(self) -> str:
        cursor = await self.db.db.execute(
            "SELECT date('now') as today"
        )
        row = await cursor.fetchone()
        return row[0] if row else "today"

    async def _count_new_leads_today(self, today: str) -> int:
        cursor = await self.db.db.execute(
            "SELECT COUNT(*) FROM leads WHERE date(created_at) = ?", (today,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def _count_emails_sent_today(self, today: str) -> int:
        cursor = await self.db.db.execute(
            "SELECT COUNT(*) FROM sequences WHERE channel = 'email' AND sent = 1 AND date(scheduled_for) = ?", (today,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def _count_whatsapp_sent_today(self, today: str) -> int:
        cursor = await self.db.db.execute(
            "SELECT COUNT(*) FROM sequences WHERE channel = 'whatsapp' AND sent = 1 AND date(scheduled_for) = ?", (today,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def _count_responses_today(self, today: str) -> Dict[str, int]:
        cursor = await self.db.db.execute(
            "SELECT classification, COUNT(*) FROM email_responses WHERE date(received_at) = ? GROUP BY classification", (today,)
        )
        rows = await cursor.fetchall()
        # Canonical classification vocabulary used by EmailResponsePoller.
        result = {"interested": 0, "question": 0, "not_interested": 0, "out_of_office": 0}
        for classification, count in rows:
            if classification in result:
                result[classification] = count
        return result

    async def _count_hot_leads(self) -> int:
        cursor = await self.db.db.execute(
            "SELECT COUNT(*) FROM leads WHERE score >= 60"
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def _count_qualified_leads(self) -> int:
        # Qualified means actually qualified (auto-replied to an interested
        # lead or accepted a Calendly slot), not merely high-scoring. The
        # previous query inflated the metric by counting every 'hot'/'warm'
        # lead. See code review B10.
        cursor = await self.db.db.execute(
            "SELECT COUNT(*) FROM leads WHERE status = 'qualified'"
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def _count_pending_followups_today(self, today: str) -> int:
        cursor = await self.db.db.execute(
            "SELECT COUNT(*) FROM sequences WHERE sent = 0 AND date(scheduled_for) = ?", (today,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    def format_whatsapp_message(self, stats: Dict[str, Any]) -> str:
        responses = stats.get("responses", {}) or {}
        lines = [
            "Daily Lead Gen Report",
            "",
            f"New leads: {stats['new_leads']}",
            f"Emails sent: {stats['emails_sent']}",
            f"WhatsApp sent: {stats['whatsapp_sent']}",
            "",
            f"Hot leads: {stats['hot_leads']}",
            f"Qualified leads: {stats['qualified_leads']}",
            "",
            "Responses today:",
            f"  Interested: {responses.get('interested', 0)}",
            f"  Questions: {responses.get('question', 0)}",
            f"  Not interested: {responses.get('not_interested', 0)}",
            f"  OOO: {responses.get('out_of_office', 0)}",
            "",
            f"Pending follow-ups: {stats['pending_followups']}",
        ]
        return "\n".join(lines)

    async def send_to_owner(self, stats: Dict[str, Any]) -> bool:
        owner_phone = os.getenv("OWNER_PHONE", "")
        if not owner_phone or not self.whatsapp_bot or not self.whatsapp_bot.page:
            logger.warning("Owner phone or WhatsApp bot not configured")
            return False
        
        message = self.format_whatsapp_message(stats)
        try:
            await self.whatsapp_bot.send_message(owner_phone, message)
            logger.info(f"Daily summary sent to {owner_phone}")
            return True
        except Exception as exc:
            logger.error(f"Failed to send daily summary: {exc}")
            return False

    async def run_and_send(self) -> bool:
        stats = await self.generate_summary()
        return await self.send_to_owner(stats)