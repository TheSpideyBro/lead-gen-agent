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
        
        cursor = await self.db.db.execute("SELECT COUNT(*) FROM leads WHERE status = 'qualified'")
        stats["qualified_leads"] = (await cursor.fetchone())[0]
        
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
        
        axes[0].pie(
            [stats.get("hot_leads", 0), stats.get("qualified_leads", 0), stats.get("total_leads", 0) - stats.get("hot_leads", 0) - stats.get("qualified_leads", 0)],
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