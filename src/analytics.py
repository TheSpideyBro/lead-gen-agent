import csv
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

    # ===== GLOBAL analytics (Section 7) =======================================
    # Each query is guarded so it degrades to empty on a DB that hasn't run the
    # migration yet (region/icp_tier columns may not exist).

    async def _safe_fetchall(self, sql, params=()):
        try:
            cur = await self.db.db.execute(sql, params)
            return await cur.fetchall()
        except Exception as exc:
            logger.warning("analytics query skipped: %s", exc)
            return []

    async def leads_by_country(self, limit: int = 10):
        """Top-N countries by lead count (country stored in leads.location)."""
        return await self._safe_fetchall(
            "SELECT COALESCE(NULLIF(TRIM(location), ''), 'Unknown') AS country, COUNT(*) AS n "
            "FROM leads GROUP BY country ORDER BY n DESC LIMIT ?", (limit,))

    async def response_rate_by_region(self):
        """Engaged (qualified/hot/booking) share per region — heatmap-style table."""
        rows = await self._safe_fetchall(
            "SELECT COALESCE(NULLIF(region, ''), 'Unknown') AS r, "
            "COUNT(*) AS total, "
            "SUM(CASE WHEN status IN ('qualified','hot','booking_sent') THEN 1 ELSE 0 END) AS engaged "
            "FROM leads GROUP BY r ORDER BY total DESC")
        return [(r, total, engaged, round(100 * engaged / total, 1) if total else 0.0)
                for (r, total, engaged) in rows]

    async def best_industry(self):
        rows = await self._safe_fetchall(
            "SELECT COALESCE(NULLIF(industry, ''), 'Unknown') AS ind, COUNT(*) AS n "
            "FROM leads WHERE status IN ('qualified','hot','booking_sent') "
            "GROUP BY ind ORDER BY n DESC LIMIT 1")
        return rows[0] if rows else None

    async def channel_by_region(self):
        return await self._safe_fetchall(
            "SELECT COALESCE(NULLIF(l.region,''),'Unknown') AS r, o.channel, COUNT(*) AS n "
            "FROM outreach o JOIN leads l ON o.lead_id = l.id "
            "GROUP BY r, o.channel ORDER BY r, n DESC")

    async def time_of_day_performance(self):
        """Which local hour produces the most replies (by reply timestamp)."""
        return await self._safe_fetchall(
            "SELECT strftime('%H', received_at) AS hr, COUNT(*) AS n "
            "FROM email_responses GROUP BY hr ORDER BY n DESC LIMIT 5")

    async def icp_tier_conversion(self):
        """Tier 1 vs Tier 2 response/qualify rate."""
        return await self._safe_fetchall(
            "SELECT COALESCE(NULLIF(icp_tier,''),'Untiered') AS tier, COUNT(*) AS total, "
            "SUM(CASE WHEN status IN ('qualified','hot','booking_sent') THEN 1 ELSE 0 END) AS engaged "
            "FROM leads GROUP BY tier ORDER BY tier")

    async def weekly_trend(self, weeks: int = 4):
        since = (datetime.now() - timedelta(weeks=weeks)).strftime("%Y-%m-%d")
        leads = await self._safe_fetchall(
            "SELECT strftime('%Y-%W', created_at) AS wk, COUNT(*) FROM leads "
            "WHERE created_at >= ? GROUP BY wk ORDER BY wk", (since,))
        emails = await self._safe_fetchall(
            "SELECT strftime('%Y-%W', sent_at) AS wk, COUNT(*) FROM outreach "
            "WHERE channel='email' AND sent_at >= ? GROUP BY wk ORDER BY wk", (since,))
        responses = await self._safe_fetchall(
            "SELECT strftime('%Y-%W', received_at) AS wk, COUNT(*) FROM responses "
            "WHERE received_at >= ? GROUP BY wk ORDER BY wk", (since,))
        return {"leads": leads, "emails": emails, "responses": responses}

    async def global_metrics(self) -> dict:
        return {
            "leads_by_country": await self.leads_by_country(),
            "response_rate_by_region": await self.response_rate_by_region(),
            "best_industry": await self.best_industry(),
            "channel_by_region": await self.channel_by_region(),
            "time_of_day": await self.time_of_day_performance(),
            "icp_tier_conversion": await self.icp_tier_conversion(),
            "weekly_trend": await self.weekly_trend(),
        }

    async def country_bar_chart(self):
        """Top-10 countries bar chart (Section 7)."""
        rows = await self.leads_by_country(10)
        if not rows:
            return None
        countries = [r[0] for r in rows]
        counts = [r[1] for r in rows]
        plt.figure(figsize=(10, 5))
        plt.barh(countries[::-1], counts[::-1])
        plt.title("Leads by Country (Top 10)")
        plt.xlabel("Leads")
        plt.tight_layout()
        path = self.output_dir / "leads_by_country.png"
        plt.savefig(path)
        plt.close()
        return path

    async def weekly_leaderboard(self, limit: int = 5):
        """Top leads this week. Returns (rows, csv_path, whatsapp_text)."""
        rows = await self._safe_fetchall(
            "SELECT company_name, COALESCE(contact_name,''), COALESCE(location,''), "
            "score, status FROM leads WHERE created_at >= date('now','-7 days') "
            "ORDER BY score DESC LIMIT ?", (limit,))

        csv_path = self.output_dir / "weekly_leaderboard.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["company", "contact", "country", "score", "status"])
            writer.writerows(rows)

        lines = ["*Top leads this week*"]
        for i, (company, contact, country, score, status) in enumerate(rows, 1):
            lines.append(f"{i}. {company} ({country or 'N/A'}) — score {score} [{status}]")
        if len(lines) == 1:
            lines.append("No new leads this week.")
        return rows, csv_path, "\n".join(lines)