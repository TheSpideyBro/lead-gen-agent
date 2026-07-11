import aiosqlite
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from src.utils.validators import normalize_phone

logger = logging.getLogger(__name__)


def get_db_path() -> Path:
    db_path = os.getenv("LEAD_DB_PATH", "data/lead_bot.db")
    p = Path(db_path)
    # Ensure the parent directory exists so aiosqlite can create the file
    # on first run, even if .gitkeep has not been committed.
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


DB_PATH = get_db_path()


class LeadDatabase:
    def __init__(self):
        self.db: Optional[aiosqlite.Connection] = None

    async def connect(self):
        self.db = await aiosqlite.connect(str(DB_PATH))
        await self.db.execute("PRAGMA foreign_keys = ON")
        # A2 fix: Enable WAL mode for better concurrent read performance
        await self.db.execute("PRAGMA journal_mode = WAL")
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
                phone_normalized TEXT,
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

            CREATE TABLE IF NOT EXISTS sequences (
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
            
            CREATE TABLE IF NOT EXISTS whatsapp_responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER,
                phone TEXT,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                body TEXT,
                classification TEXT,
                message_id TEXT UNIQUE  -- Meta message id for dedup
            );

            CREATE TABLE IF NOT EXISTS email_opens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER,
                sequence_id INTEGER,
                opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ip_address TEXT
            );

            CREATE TABLE IF NOT EXISTS global_unsubscribe (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT,
                phone TEXT,
                unsubscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reason TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
            CREATE INDEX IF NOT EXISTS idx_unsub_email ON global_unsubscribe(email);
            CREATE INDEX IF NOT EXISTS idx_unsub_phone ON global_unsubscribe(phone);
            CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(score);
            CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);
            CREATE INDEX IF NOT EXISTS idx_opens_lead ON email_opens(lead_id);
            CREATE INDEX IF NOT EXISTS idx_wa_resp_msg ON whatsapp_responses(message_id);
            -- Idempotency: a given (lead, channel, step) is queued at most once.
            -- Two parallel cron invocations used to send the same email twice.
            -- See code review B7.
            CREATE UNIQUE INDEX IF NOT EXISTS uniq_seq_lead_channel_step
                ON sequences(lead_id, channel, step);
        """)
        await self.db.commit()

        # S3 fix: Add table for persistent IMAP message dedup
        await self.db.executescript("""
            CREATE TABLE IF NOT EXISTS imap_dedup (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                msg_hash TEXT UNIQUE NOT NULL,
                lead_id INTEGER,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_imap_hash ON imap_dedup(msg_hash);
        """)
        await self.db.commit()

    async def add_lead(self, lead_data: dict) -> int:
        cursor = await self.db.execute(
            """INSERT INTO leads (company_name, contact_name, contact_title, email, phone,
                                 website, industry, location, employees, source,
                                 phone_normalized, score)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                normalize_phone(lead_data.get("phone")),
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

    async def claim_sequence_for_send(self, sequence_id: int) -> bool:
        """Atomically claim a sequence row for sending.

        Returns True if the row was claimed (sent=0 -> sent=1), False if it was
        already claimed by another process.  This prevents duplicate sends when
        multiple cron invocations or processes run concurrently.  See code
        review B3/B4.
        """
        cursor = await self.db.execute(
            "UPDATE sequences SET sent = 1 WHERE id = ? AND sent = 0",
            (sequence_id,),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def log_outreach_and_mark_sent(self, lead_id: int, channel: str, subject: str, body: str, sequence_id: int):
        """Log an outreach send and mark the sequence row as sent, all in one transaction.

        This is the atomic counterpart to the two-step log_outreach + mark_email_sent
        that existed before.  See code review B2.
        """
        async with self.db:
            await self.db.execute(
                "INSERT INTO outreach (lead_id, channel, subject, body) VALUES (?, ?, ?, ?)",
                (lead_id, channel, subject, body),
            )
            await self.db.execute(
                "UPDATE sequences SET sent = 1 WHERE id = ?",
                (sequence_id,),
            )

    async def log_response(self, lead_id: int, response_type: str, content: str):
        await self.db.execute(
            "INSERT INTO responses (lead_id, response_type, content) VALUES (?, ?, ?)",
            (lead_id, response_type, content),
        )
        await self.db.commit()

    async def schedule_message(self, lead_id: int, channel: str, step: int, scheduled_for: str):
        # Idempotent: if a (lead, channel, step) row already exists (e.g. the
        # scheduler ran twice for the same lead), UPDATE its scheduled_for
        # instead of failing the unique index. See code review B7.
        try:
            await self.db.execute(
                "INSERT INTO sequences (lead_id, channel, step, scheduled_for) "
                "VALUES (?, ?, ?, ?)",
                (lead_id, channel, step, scheduled_for),
            )
            await self.db.commit()
        except Exception as exc:
            msg = str(exc).lower()
            if "unique" in msg or "constraint" in msg:
                await self.db.execute(
                    "UPDATE sequences SET scheduled_for = ? "
                    "WHERE lead_id = ? AND channel = ? AND step = ?",
                    (scheduled_for, lead_id, channel, step),
                )
                await self.db.commit()
            else:
                raise

    async def get_lead_by_id(self, lead_id: int) -> dict:
        cursor = await self.db.execute(
            "SELECT * FROM leads WHERE id = ?", (lead_id,)
        )
        row = await cursor.fetchone()
        if row:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))
        return {}

    async def get_pending_emails(self, limit: int = 100):
        # Cap batch size so a backlog doesn't block the event loop. See P7.
        cursor = await self.db.execute(
            "SELECT s.id, s.lead_id, s.step, l.email, l.contact_name, l.company_name "
            "FROM sequences s JOIN leads l ON s.lead_id = l.id "
            "WHERE s.channel = 'email' AND s.sent = 0 "
            "AND datetime(s.scheduled_for) <= datetime('now') "
            "ORDER BY s.scheduled_for ASC LIMIT ?",
            (limit,),
        )
        return await cursor.fetchall()

    async def get_pending_messages(self, limit: int = 100):
        cursor = await self.db.execute(
            "SELECT s.id, s.lead_id, s.channel, s.step, l.phone, l.contact_name, l.company_name "
            "FROM sequences s JOIN leads l ON s.lead_id = l.id "
            "WHERE s.channel = 'whatsapp' AND s.sent = 0 "
            "AND datetime(s.scheduled_for) <= datetime('now') "
            "ORDER BY s.scheduled_for ASC LIMIT ?",
            (limit,),
        )
        return await cursor.fetchall()

    async def mark_email_sent(self, sequence_id: int):
        await self.db.execute(
            "UPDATE sequences SET sent = 1 WHERE id = ?", (sequence_id,)
        )
        await self.db.commit()

    async def mark_message_sent(self, sequence_id: int):
        await self.db.execute(
            "UPDATE sequences SET sent = 1 WHERE id = ?", (sequence_id,)
        )
        await self.db.commit()

    async def is_seen_message_id(self, message_id: str) -> bool:
        """Return True if this Meta message.id was already processed."""
        if not message_id:
            return False
        cursor = await self.db.execute(
            "SELECT 1 FROM whatsapp_responses WHERE message_id = ? LIMIT 1",
            (message_id,),
        )
        return (await cursor.fetchone()) is not None

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

    async def get_unreplied_responses(self, limit: int = 200):
        """Get unhandled email responses with a limit to prevent memory issues.
        
        B2 fix: Added limit parameter that was previously ignored.
        """
        cursor = await self.db.execute(
            "SELECT * FROM email_responses WHERE replied = 0 ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return await cursor.fetchall()

    async def mark_response_replied(self, response_id: int):
        await self.db.execute(
            "UPDATE email_responses SET replied = 1 WHERE id = ?", (response_id,)
        )
        await self.db.commit()

    async def reschedule_sequence(self, lead_id: int, extra_days: int = 5):
        cursor = await self.db.execute(
            "SELECT step FROM sequences "
            "WHERE lead_id = ? AND channel = 'email' AND sent = 0 ORDER BY step ASC LIMIT 1",
            (lead_id,)
        )
        seq = await cursor.fetchone()
        if seq:
            new_time = (datetime.now() + timedelta(days=extra_days)).isoformat()
            await self.db.execute(
                "UPDATE sequences SET scheduled_for = ? "
                "WHERE lead_id = ? AND channel = 'email' AND sent = 0",
                (new_time, lead_id)
            )
            await self.db.commit()

    async def stop_all_sequences(self, lead_id: int):
        await self.db.execute(
            "DELETE FROM sequences WHERE lead_id = ? AND sent = 0", (lead_id,)
        )
        await self.db.commit()

    async def log_email_open(self, lead_id, sequence_id, ip_address: str = ""):
        await self.db.execute(
            "INSERT INTO email_opens (lead_id, sequence_id, ip_address) VALUES (?, ?, ?)",
            (lead_id, sequence_id, ip_address),
        )
        await self.db.execute(
            "UPDATE leads SET last_contacted = CURRENT_TIMESTAMP WHERE id = ?", (lead_id,)
        )
        await self.db.commit()

    async def has_lead_opened(self, lead_id: int) -> bool:
        cursor = await self.db.execute(
            "SELECT 1 FROM email_opens WHERE lead_id = ? LIMIT 1", (lead_id,)
        )
        return (await cursor.fetchone()) is not None

    async def get_open_stats_by_step(self):
        cursor = await self.db.execute(
            "SELECT s.step, "
            "COUNT(DISTINCT s.id) AS sent, "
            "COUNT(DISTINCT eo.sequence_id) AS opened "
            "FROM sequences s "
            "LEFT JOIN email_opens eo ON eo.sequence_id = s.id "
            "WHERE s.channel = 'email' AND s.sent = 1 "
            "GROUP BY s.step ORDER BY s.step"
        )
        return await cursor.fetchall()

    async def get_booking_pipeline(self):
        cursor = await self.db.execute(
            "SELECT id, company_name, contact_name, email, phone, status FROM leads "
            "WHERE status IN ('booking_sent', 'qualified') ORDER BY score DESC"
        )
        return await cursor.fetchall()

    async def add_unsubscribe(self, email: str = None, phone: str = None, reason: str = ""):
        """Record a global opt-out so the contact is never messaged again."""
        await self.db.execute(
            "INSERT INTO global_unsubscribe (email, phone, reason) VALUES (?, ?, ?)",
            (email, phone, reason),
        )
        await self.db.commit()

    async def is_unsubscribed(self, email: str = None, phone: str = None) -> bool:
        """True if this email or phone appears in the global suppression list."""
        if not email and not phone:
            return False
        cursor = await self.db.execute(
            "SELECT 1 FROM global_unsubscribe WHERE "
            "(email IS NOT NULL AND email = ?) OR (phone IS NOT NULL AND phone = ?) LIMIT 1",
            (email, phone),
        )
        return (await cursor.fetchone()) is not None

    # S3: IMAP dedup methods
    async def imap_dedup_seen(self, msg_hash: str) -> bool:
        """Check if this IMAP message hash was already processed."""
        cursor = await self.db.execute(
            "SELECT 1 FROM imap_dedup WHERE msg_hash = ? LIMIT 1", (msg_hash,))
        return (await cursor.fetchone()) is not None

    async def imap_dedup_record(self, msg_hash: str, lead_id: int = None):
        """Record that this IMAP message was processed."""
        try:
            await self.db.execute(
                "INSERT INTO imap_dedup (msg_hash, lead_id) VALUES (?, ?)",
                (msg_hash, lead_id),
            )
            await self.db.commit()
        except Exception:
            # Unique constraint violation = already recorded (idempotent)
            pass

    # Columns added by src/db/migrate.py — allowed targets for enrichment writes.
    # S4 fix: strict allowlist prevents SQL injection via dynamic column names.
    GLOBAL_COLUMNS: frozenset = frozenset({
        "icp_score", "icp_tier", "detected_timezone",
        "detected_language", "email_verified", "region", "funding_stage",
    })

    async def update_lead_global(self, lead_id: int, **fields):
        """Update the global enrichment columns for a lead.

        Silently no-ops on a DB that hasn't been migrated yet (columns absent),
        so callers don't need to know the schema version.

        S4 fix: only columns in GLOBAL_COLUMNS are accepted; any unexpected key
        is silently dropped rather than interpolated into SQL.
        """
        cols = {k: v for k, v in fields.items()
                if k in self.GLOBAL_COLUMNS and v is not None}
        if not cols:
            return
        # Build parameterised assignment fragments from the whitelist only.
        assignments = ", ".join(f"{c} = ?" for c in sorted(cols))
        values = [cols[c] for c in sorted(cols)]
        try:
            await self.db.execute(
                f"UPDATE leads SET {assignments} WHERE id = ?",
                (*values, lead_id))
            await self.db.commit()
        except Exception as exc:
            logger.warning("update_lead_global skipped (run migration?): %s", exc)