import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("data/lead_bot.log"),
    ]
)
logger = logging.getLogger(__name__)

from src.database import LeadDatabase
from src.ai_client import AIClient
from src.scrapers.prospect_scraper import LeadScraper
from src.outreach.email_generator import MessageGenerator, OutreachSequence
from src.outreach.email_sender import EmailSender, LeadScorer
from src.outreach.email_response_handler import EmailResponsePoller
from src.whatsapp_bot import WhatsAppBot
from src.analytics import Analytics


async def run_prospecting(db, scraper, scorer, outbound):
    profile_path = Path(__file__).parent / "config" / "agency_profile.json"
    with open(profile_path, encoding="utf-8") as f:
        profile = json.load(f)
    
    industries = profile.get("target_client_profile", {}).get("industries", [])
    locations = profile.get("target_client_profile", {}).get("geographic_focus", [])
    
    leads = await scraper.find_prospects(industries, locations)
    
    for lead in leads:
        lead_dict = {
            "company_name": lead.company_name,
            "contact_name": lead.contact_name,
            "contact_title": lead.contact_title,
            "email": lead.email,
            "phone": lead.phone,
            "website": lead.website,
            "industry": lead.industry,
            "location": lead.location,
            "employees": lead.employees,
            "source": lead.source,
        }
        
        score = scorer.score_lead(lead_dict)
        category = scorer.categorize_lead(score)
        lead_dict["score"] = score
        
        lead_id = await db.add_lead(lead_dict)
        await db.update_lead_status(lead_id, category)
        
        if lead.email:
            await outbound.schedule_sequence(lead_id, "email")
        if lead.phone:
            await outbound.schedule_sequence(lead_id, "whatsapp")
        
        logger.info(f"Added lead: {lead.company_name} (Score: {score}, Category: {category})")
    
    return len(leads)


async def run_outreach(db, outbound, channel="email"):
    sent_count = 0
    if channel == "email":
        sender = EmailSender()
        sent = await outbound.process_pending_emails(sender)
        print(f"Sent {sent} emails")
        if sent > 0:
            await sender.close()
        sent_count = sent
    elif channel == "whatsapp":
        sent = await outbound.process_pending_whatsapp()
        print(f"Sent {sent} WhatsApp messages")
        sent_count = sent
    return sent_count


async def check_email_responses(poller):
    count = await poller.check_for_replies()
    print(f"Processed {count} email replies")
    
    responses = await poller.get_pending_responses()
    for r in responses[:5]:
        print(f" - Response ID {r[0]}: {r[3]} ({r[4] if len(r) > 4 else 'unknown'})")


async def check_whatsapp_responses(whatsapp):
    if not whatsapp.page:
        print("WhatsApp not connected. Connect first (option 7).")
        return
    
    processed = await whatsapp.poll_new_messages()
    print(f"Processed {processed} WhatsApp messages")
    
    cursor = await whatsapp.db.db.execute(
        "SELECT id, phone, body, classification FROM whatsapp_responses ORDER BY received_at DESC LIMIT 5"
    )
    responses = await cursor.fetchall()
    for r in responses:
        print(f" - WhatsApp {r[1]}: {r[3]} ({r[2][:50] if r[2] else 'no body'})")


async def main_loop():
    db = LeadDatabase()
    await db.connect()
    logger.info("Database connected")
    
    ai = AIClient()
    scraper = LeadScraper()
    scorer = LeadScorer()
    msg_gen = MessageGenerator(ai)
    whatsapp = WhatsAppBot()
    whatsapp.db = db
    whatsapp.ai = ai
    analytics = Analytics(db)
    outbound = OutreachSequence(db, msg_gen, whatsapp)
    email_poller = EmailResponsePoller(db, ai)
    
    show_whatsapp_menu = False
    
    while True:
        print("\n=== Lead Gen Agent Menu ===")
        print("1. Run prospecting (find new leads)")
        print("2. Send email outreach")
        print("3. Send WhatsApp outreach")
        print("4. View hot leads")
        print("5. View pending followups")
        print("6. Daily report")
        if not show_whatsapp_menu:
            print("7. Connect WhatsApp (one-time setup)")
        print("8. Check email responses")
        print("9. Check WhatsApp responses")
        print("10. Exit")
        
        choice = input("Select option: ").strip()
        
        try:
            if choice == "1":
                count = await run_prospecting(db, scraper, scorer, outbound)
                print(f"Found {count} prospects")
            
            elif choice == "2":
                sent = await run_outreach(db, outbound, "email")
                print(f"Sent {sent} emails")
            
            elif choice == "3":
                sent = await run_outreach(db, outbound, "whatsapp")
                print(f"Sent {sent} WhatsApp messages")
            
            elif choice == "4":
                leads = await db.get_leads_by_status("hot")
                for lead in leads[:10]:
                    if len(lead) > 1:
                        print(f" - {lead[1]} (Score: {lead[9] if len(lead) > 9 else 'N/A'})")
            
            elif choice == "5":
                print("\nPending emails:")
                emails = await db.get_pending_emails()
                for e in emails[:5]:
                    if len(e) > 1:
                        print(f" - Lead {e[1]}: Step {e[2] if len(e) > 2 else 'unknown'}")
                
                print("\nPending WhatsApp messages:")
                msgs = await db.get_pending_messages()
                for m in msgs[:5]:
                    if len(m) > 1:
                        print(f" - Lead {m[1]}: Step {m[2] if len(m) > 2 else 'unknown'}")
            
            elif choice == "6":
                chart, stats = await analytics.generate_daily_report()
                print(f"Report saved: {chart}")
                print(f"Stats: {stats}")
            
            elif choice == "7" and not show_whatsapp_menu:
                print("Connecting WhatsApp Web (browser will open)...")
                await whatsapp.start()
                show_whatsapp_menu = True
                print("WhatsApp connected! QR code scanned.")
            
            elif choice == "8":
                await check_email_responses(email_poller)
            
            elif choice == "9":
                await check_whatsapp_responses(whatsapp)
            
            elif choice == "10":
                await db.close()
                break
        except Exception as exc:
            logger.error(f"Error: {exc}")
            print(f"Error: {exc}")


if __name__ == "__main__":
    asyncio.run(main_loop())