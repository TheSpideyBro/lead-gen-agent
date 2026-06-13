import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
import matplotlib.pyplot as plt

logger = logging.getLogger(__name__)


class Analytics:
    def __init__(self, db):
        self.db = db
        self.output_dir = Path(__file__).parent.parent / "output" / "reports"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def get_stats(self) -> dict:
        stats = {}
        
        cursor = await self.db.db.execute("SELECT COUNT(*) FROM leads")
        stats["total_leads"] = (await cursor.fetchone())[0]
        
        cursor = await self.db.db.execute("SELECT COUNT(*) FROM leads WHERE status = 'hot'")
        stats["hot_leads"] = (await cursor.fetchone())[0]

        # "qualified" must mean a lead that has actually been qualified
        # (auto-replied to an interested response, accepted a Calendly slot,
        # etc.) — not merely a high-scoring tier. See code review B10.
        cursor = await self.db.db.execute("SELECT COUNT(*) FROM leads WHERE status = 'qualified'")
        stats["qualified_leads"] = (await cursor.fetchone())[0]

        cursor = await self.db.db.execute("SELECT COUNT(*) FROM leads WHERE status = 'booking_sent'")
        stats["booking_sent_leads"] = (await cursor.fetchone())[0]
        
        cursor = await self.db.db.execute("SELECT COUNT(*) FROM outreach WHERE channel = 'email'")
        stats["emails_sent"] = (await cursor.fetchone())[0]
        
        cursor = await self.db.db.execute("SELECT COUNT(*) FROM outreach WHERE channel = 'whatsapp'")
        stats["whatsapp_sent"] = (await cursor.fetchone())[0]
        
        cursor = await self.db.db.execute("SELECT COUNT(*) FROM responses")
        stats["responses_received"] = (await cursor.fetchone())[0]
        
        return stats

    async def generate_daily_report(self):
        stats = await self.get_stats()

        fig, axes = plt.subplots(1, 2, figsize=(12, 5))

        hot = stats.get("hot_leads", 0)
        qualified = stats.get("qualified_leads", 0)
        other = stats.get("total_leads", 0) - hot - qualified
        pie_values = [max(0, hot), max(0, qualified), max(0, other)]
        if sum(pie_values) == 0:
            # matplotlib divides by the total, producing NaN on an all-zero pie
            axes[0].text(0.5, 0.5, "No leads yet", ha="center", va="center")
            axes[0].axis("off")
        else:
            axes[0].pie(
                pie_values,
                labels=["Hot Leads", "Qualified", "Other"],
                autopct="%1.1f%%",
            )
        axes[0].set_title("Lead Distribution")
        
        axes[1].bar(
            ["Emails Sent", "WhatsApp Sent", "Responses"], 
            [stats.get("emails_sent", 0), stats.get("whatsapp_sent", 0), stats.get("responses_received", 0)]
        )
        axes[1].set_title("Outreach Activity")
        
        plt.tight_layout()
        chart_path = self.output_dir / "daily_report.png"
        plt.savefig(chart_path)
        plt.close()
        
        return chart_path, stats