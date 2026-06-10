import aiosqlite
import asyncio
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "lead_bot.db"


class LeadDatabase:
    def __init__(self):
        self.db: Optional[aiosqlite.Connection] = None

    async def connect(self):
        self.db = await aiosqlite.connect(str(DB_PATH))
        await self.db.execute("PRAGMA foreign_keys = ON")
        await self._create_tables()

    async def close(self):
        if self.db:
            await self.db.close()

    async def _create_tables(self):
        await self.db.executescript("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT NOT NULL,
                contact_name TEXT,
                contact_title TEXT,
                email TEXT,
                phone TEXT,
                website TEXT,
                industry TEXT,
                location TEXT,
                employees INTEGER,
                source TEXT,
                score INTEGER DEFAULT 0,
                status TEXT DEFAULT 'new',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_contacted TIMESTAMP,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS outreach (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                subject TEXT,
                body TEXT,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (lead_id) REFERENCES leads(id)
            );

            CREATE TABLE IF NOT EXISTS responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER NOT NULL,
                response_type TEXT,
                content TEXT,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (lead_id) REFERENCES leads(id)
            );

            CREATE TABLE IF NOT EXISTS email_sequences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER NOT NULL,
                step INTEGER NOT NULL,
                scheduled_for TIMESTAMP,
                sent BOOLEAN DEFAULT 0,
                FOREIGN KEY (lead_id) REFERENCES leads(id)
            );

            CREATE TABLE IF NOT EXISTS message_sequences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER NOT NULL,
                channel TEXT,
                step INTEGER NOT NULL,
                scheduled_for TIMESTAMP,
                sent BOOLEAN DEFAULT 0,
                FOREIGN KEY (lead_id) REFERENCES leads(id)
            );
            
            CREATE TABLE IF NOT EXISTS email_responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER NOT NULL,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                subject TEXT,
                body TEXT,
                classification TEXT,
                replied BOOLEAN DEFAULT 0,
                FOREIGN KEY (lead_id) REFERENCES leads(id)
            );

            CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
            CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(score);
            CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);
        """)
        await self.db.commit()

    async def add_lead(self, lead_data: dict) -> int:
        cursor = await self.db.execute(
            """INSERT INTO leads (company_name, contact_name, contact_title, email, phone, 
                                 website, industry, location, employees, source, score)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                lead_data.get("company_name"),
                lead_data.get("contact_name"),
                lead_data.get("contact_title"),
                lead_data.get("email"),
                lead_data.get("phone"),
                lead_data.get("website"),
                lead_data.get("industry"),
                lead_data.get("location"),
                lead_data.get("employees"),
                lead_data.get("source"),
                lead_data.get("score", 0),
            ),
        )
        await self.db.commit()
        return cursor.lastrowid

    async def update_lead_score(self, lead_id: int, score: int):
        await self.db.execute(
            "UPDATE leads SET score = ? WHERE id = ?", (score, lead_id)
        )
        await self.db.commit()

    async def get_leads_by_status(self, status: str = "new"):
        cursor = await self.db.execute(
            "SELECT * FROM leads WHERE status = ? ORDER BY score DESC", (status,)
        )
        return await cursor.fetchall()

    async def update_lead_status(self, lead_id: int, status: str):
        await self.db.execute(
            "UPDATE leads SET status = ? WHERE id = ?", (status, lead_id)
        )
        await self.db.commit()

    async def log_outreach(self, lead_id: int, channel: str, subject: str, body: str):
        await self.db.execute(
            "INSERT INTO outreach (lead_id, channel, subject, body) VALUES (?, ?, ?, ?)",
            (lead_id, channel, subject, body),
        )
        await self.db.commit()

    async def log_response(self, lead_id: int, response_type: str, content: str):
        await self.db.execute(
            "INSERT INTO responses (lead_id, response_type, content) VALUES (?, ?, ?)",
            (lead_id, response_type, content),
        )
        await self.db.commit()

    async def schedule_email(self, lead_id: int, step: int, scheduled_for: str):
        await self.db.execute(
            "INSERT INTO email_sequences (lead_id, step, scheduled_for) VALUES (?, ?, ?)",
            (lead_id, step, scheduled_for),
        )
        await self.db.commit()

    async def schedule_message(self, lead_id: int, channel: str, step: int, scheduled_for: str):
        await self.db.execute(
            "INSERT INTO message_sequences (lead_id, channel, step, scheduled_for) VALUES (?, ?, ?, ?)",
            (lead_id, channel, step, scheduled_for),
        )
        await self.db.commit()

    async def get_lead_by_id(self, lead_id: int) -> dict:
        cursor = await self.db.execute(
            "SELECT * FROM leads WHERE id = ?", (lead_id,)
        )
        row = await cursor.fetchone()
        if row:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))
        return {}

    async def get_pending_emails(self):
        cursor = await self.db.execute(
            "SELECT es.id, es.lead_id, es.step, l.email, l.contact_name, l.company_name "
            "FROM email_sequences es JOIN leads l ON es.lead_id = l.id "
            "WHERE sent = 0 AND datetime(scheduled_for) <= datetime('now')"
        )
        return await cursor.fetchall()

    async def get_pending_messages(self):
        cursor = await self.db.execute(
            "SELECT ms.id, ms.lead_id, ms.channel, ms.step, l.phone, l.contact_name, l.company_name "
            "FROM message_sequences ms JOIN leads l ON ms.lead_id = l.id "
            "WHERE sent = 0 AND datetime(scheduled_for) <= datetime('now')"
        )
        return await cursor.fetchall()

    async def mark_email_sent(self, sequence_id: int):
        await self.db.execute(
            "UPDATE email_sequences SET sent = 1 WHERE id = ?", (sequence_id,)
        )
        await self.db.commit()

    async def mark_message_sent(self, sequence_id: int):
        await self.db.execute(
            "UPDATE message_sequences SET sent = 1 WHERE id = ?", (sequence_id,)
        )
        await self.db.commit()

    async def get_all_leads_with_email(self):
        cursor = await self.db.execute(
            "SELECT id, email FROM leads WHERE email IS NOT NULL AND status != 'unsubscribed'"
        )
        return await cursor.fetchall()

    async def log_email_response(self, lead_id: int, subject: str, body: str, classification: str):
        await self.db.execute(
            "INSERT INTO email_responses (lead_id, subject, body, classification) VALUES (?, ?, ?, ?)",
            (lead_id, subject, body, classification)
        )
        await self.db.commit()

    async def get_unreplied_responses(self):
        cursor = await self.db.execute(
            "SELECT * FROM email_responses WHERE replied = 0"
        )
        return await cursor.fetchall()

    async def mark_response_replied(self, response_id: int):
        await self.db.execute(
            "UPDATE email_responses SET replied = 1 WHERE id = ?", (response_id,)
        )
        await self.db.commit()

    async def reschedule_sequence(self, lead_id: int, extra_days: int = 5):
        cursor = await self.db.execute(
            "SELECT step FROM email_sequences WHERE lead_id = ? AND sent = 0 ORDER BY step ASC LIMIT 1",
            (lead_id,)
        )
        seq = await cursor.fetchone()
        if seq:
            new_time = (datetime.now() + timedelta(days=extra_days)).isoformat()
            await self.db.execute(
                "UPDATE email_sequences SET scheduled_for = ? WHERE lead_id = ? AND sent = 0",
                (new_time, lead_id)
            )
            await self.db.commit()

    async def stop_all_sequences(self, lead_id: int):
        await self.db.execute(
            "DELETE FROM email_sequences WHERE lead_id = ? AND sent = 0", (lead_id,)
        )
        await self.db.execute(
            "DELETE FROM message_sequences WHERE lead_id = ? AND sent = 0", (lead_id,)
        )
        await self.db.commit()