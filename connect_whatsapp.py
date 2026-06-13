import asyncio
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from src.whatsapp_bot import WhatsAppBot
from src.database import LeadDatabase

async def connect_whatsapp():
    db = LeadDatabase()
    await db.connect()
    print("Database connected")

    whatsapp = WhatsAppBot()
    try:
        print("Starting WhatsApp Web... A browser will open for QR scan.")
        await whatsapp.start()
        print("WhatsApp connected successfully!")
        input("\nPress Enter to exit...")
    finally:
        # Always close the browser, even if QR scan fails, so the user
        # doesn't end up with a leaked Playwright process.
        try:
            await whatsapp.close()
        finally:
            await db.close()

if __name__ == "__main__":
    asyncio.run(connect_whatsapp())