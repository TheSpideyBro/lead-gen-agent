"""Idempotent schema migration for the GLOBAL upgrade.

Adds the new leads columns (and ensures the global_unsubscribe table) WITHOUT
losing existing data. Safe to run repeatedly: each ALTER is guarded by checking
the current column set first. Run standalone:

    python -m src.db.migrate
"""
import asyncio
import logging

import aiosqlite

from src.database import DB_PATH

logger = logging.getLogger(__name__)

# New columns on the leads table -> SQL type.
NEW_LEAD_COLUMNS = {
    "icp_score": "INTEGER",
    "icp_tier": "TEXT",
    "detected_timezone": "TEXT",
    "detected_language": "TEXT",
    "email_verified": "INTEGER DEFAULT 0",
    "region": "TEXT",
    "funding_stage": "TEXT",
    "phone_normalized": "TEXT",
}

GLOBAL_UNSUBSCRIBE_DDL = """
CREATE TABLE IF NOT EXISTS global_unsubscribe (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT,
    phone TEXT,
    unsubscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reason TEXT
)
"""


async def _existing_columns(db, table: str) -> set:
    cursor = await db.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in await cursor.fetchall()}


async def migrate(db_path=None) -> list:
    """Apply the migration. Returns the list of columns actually added."""
    path = str(db_path or DB_PATH)
    added = []
    async with aiosqlite.connect(path) as db:
        existing = await _existing_columns(db, "leads")
        for col, col_type in NEW_LEAD_COLUMNS.items():
            if col not in existing:
                await db.execute(f"ALTER TABLE leads ADD COLUMN {col} {col_type}")
                added.append(col)
                logger.info("Added leads.%s", col)

        await db.execute(GLOBAL_UNSUBSCRIBE_DDL)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_unsub_email ON global_unsubscribe(email)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_unsub_phone ON global_unsubscribe(phone)")
        # 4.3 fix: add indexes for frequent query patterns
        await db.execute("CREATE INDEX IF NOT EXISTS idx_seq_pending ON sequences(channel, sent, scheduled_for)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_resp_replied ON email_responses(replied)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_wa_resp_received ON whatsapp_responses(received_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_leads_phone_norm ON leads(phone_normalized)")
        await db.commit()

    if added:
        print(f"Migration complete. Added columns: {', '.join(added)}")
    else:
        print("Migration complete. Schema already up to date.")
    return added


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(migrate())
