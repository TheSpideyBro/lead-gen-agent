import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()

# Force UTF-8 on stdout/stderr so the 🌍 and other non-ASCII characters
# in the GLOBAL banner don't crash on Windows cmd.exe (cp1252 default).
# Reconfigure is a no-op if the stream is already UTF-8 (POSIX, modern
# Windows Terminal, GitHub Actions).  See code review smoke test.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Ensure runtime data/output/log directories exist before any submodule tries
# to open a file inside them.  See data/.gitkeep for the empty-directory
# sentinel that is actually tracked.
for _dir in ("data", "data/linkedin", "data/whatsapp", "output/reports"):
    Path(_dir).mkdir(parents=True, exist_ok=True)
del _dir

from src.logging_setup import setup_logging  # noqa: E402  (after Path bootstrap)
setup_logging()
logger = logging.getLogger(__name__)

from src.database import LeadDatabase
from src.ai_client import AIClient
from src.scrapers.prospect_scraper import LeadScraper
from src.scrapers.linkedin_scraper import LinkedInScraper
from src.outreach.email_generator import MessageGenerator, OutreachSequence
from src.outreach.email_sender import EmailSender, LeadScorer
from src.outreach.email_response_handler import EmailResponsePoller
from src.whatsapp_bot import WhatsAppBot
from src.analytics import Analytics
from src.tracking.server import TrackingServer, get_tracking_port
from src.reports.daily_summary import DailySummary
from src.scoring.icp_scorer import ICPScorer
from src.scheduling.timezone_scheduler import TimezoneScheduler
from src.language.lang_handler import LangHandler
from src.utils.api_usage import APIUsageTracker
from src.db.migrate import migrate


def load_global_targeting() -> dict:
    path = Path(__file__).parent / "config" / "global_targeting.json"
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def global_status_lines(usage: APIUsageTracker) -> list:
    """Lines for the GLOBAL MODE banner: active sources + today's API usage."""
    lines = ["", "🌍 GLOBAL MODE — firmographic, multi-source, worldwide", "Active lead sources:"]
    lines.append(f"  Apollo      : {'ON' if os.getenv('APOLLO_API_KEY') else 'off (set APOLLO_API_KEY)'}")
    lines.append(f"  GitHub      : {'ON (token)' if os.getenv('GITHUB_TOKEN') else 'ON (anon, 60/hr)'}")
    lines.append(f"  ProductHunt : {'ON' if os.getenv('PRODUCTHUNT_TOKEN') else 'off (set PRODUCTHUNT_TOKEN)'}")
    lines.append("  Google/DDG  : fallback")
    lines.append(f"WhatsApp provider: {os.getenv('WHATSAPP_PROVIDER', 'web')}  |  "
                 f"Language: {os.getenv('OUTREACH_LANGUAGE', 'auto')}  |  "
                 f"GDPR mode: {os.getenv('GDPR_MODE', 'false')}")
    lines.append("Today's API usage (used/limit):")
    for source, info in usage.snapshot().items():
        flag = "  ⚠" if info["limit"] and info["used"] >= 0.8 * info["limit"] else ""
        lines.append(f"  {source:<14}{info['used']}/{info['limit']}{flag}")
    return lines


async def run_prospecting(db, c):
    """GLOBAL prospecting: fan out to all configured sources, ICP-score, enrich
    (timezone/language/region), and auto-contact only Tier 1/2 leads."""
    scraper, scorer, outbound = c["scraper"], c["scorer"], c["outbound"]
    icp, tz, lang = c["icp"], c["tz"], c["lang"]

    targeting = load_global_targeting()
    leads = await scraper.find_global_prospects(targeting)

    # Fallback to the legacy location-based search if no global source returned.
    if not leads:
        logger.info("No global-source leads (keys unset?) — falling back to Google/DDG")
        profile_path = Path(__file__).parent / "config" / "agency_profile.json"
        with open(profile_path, encoding="utf-8") as f:
            profile = json.load(f)
        industries = profile.get("target_client_profile", {}).get("industries", [])
        locations = profile.get("target_client_profile", {}).get("geographic_focus", [])
        leads = await scraper.find_prospects(industries, locations)

    min_score = targeting.get("min_score_to_contact", 40)
    for lead in leads:
        lead_dict = {
            "company_name": lead.company_name,
            "contact_name": lead.contact_name,
            "contact_title": lead.contact_title,
            "email": lead.email,
            "phone": lead.phone,
            "website": lead.website,
            "industry": lead.industry,
            "location": lead.location or lead.country,
            "employees": lead.employees,
            "source": lead.source,
        }
        legacy_score = scorer.score_lead(lead_dict)
        lead_dict["score"] = legacy_score

        lead_id = await db.add_lead(lead_dict)
        lead_dict["id"] = lead_id
        category = scorer.categorize_lead(legacy_score)
        await db.update_lead_status(lead_id, category)

        # ICP scoring + enrichment (tech detection off for bulk speed/safety).
        icp_input = {**lead_dict, "linkedin_url": lead.linkedin_url,
                     "funding_stage": lead.funding_stage, "signals": lead.signals}
        icp_score = await icp.score_lead(icp_input, detect_tech=False)
        tier = icp.get_icp_tier(icp_score)
        country = lead.country or lead.location
        country_code = tz.country_to_code(country)
        await db.update_lead_global(
            lead_id,
            icp_score=icp_score,
            icp_tier=tier,
            detected_timezone=tz.detect_timezone(country),
            detected_language=lang.language_for_country(country),
            region=outbound.compliance.region_for_country(country_code),
            funding_stage=lead.funding_stage,
        )

        # Only auto-contact Tier 1/2 leads above the min score (Section 2).
        if not icp.should_auto_contact(tier) or icp_score < min_score:
            logger.info("Lead %s — %s (ICP %d) not auto-contacted",
                        lead.company_name, tier, icp_score)
            continue

        if category == "hot":
            if lead.email:
                await outbound.send_booking_outreach(lead_dict, "email")
            if lead.phone:
                await outbound.send_booking_outreach(lead_dict, "whatsapp")
        else:
            if lead.email:
                await outbound.schedule_sequence(lead_id, "email")
            if lead.phone:
                await outbound.schedule_sequence(lead_id, "whatsapp")
        logger.info("Added lead: %s (%s, ICP %d, %s)",
                    lead.company_name, category, icp_score, tier)

    return len(leads)


async def run_outreach(db, outbound, channel="email"):
    sent_count = 0
    if channel == "email":
        # process_pending_emails will fall back to the singleton sender the
        # outbound was constructed with, so we no longer spin up a new SMTP
        # connection per call.  See code review B10.
        sent = await outbound.process_pending_emails()
        print(f"Sent {sent} emails")
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


async def run_linkedin_prospecting(db, scraper, scorer, linkedin_scraper, outbound):
    profile_path = Path(__file__).parent / "config" / "agency_profile.json"
    with open(profile_path, encoding="utf-8") as f:
        profile = json.load(f)
    
    industries = profile.get("target_client_profile", {}).get("industries", [])
    locations = profile.get("target_client_profile", {}).get("geographic_focus", [])
    
    total_found = 0
    for niche in industries[:2]:
        for loc in locations[:2]:
            print(f"LinkedIn search: {niche} in {loc}")
            leads = await linkedin_scraper.search_prospects(niche, loc, 5)
            
            for lead in leads:
                lead_dict = {
                    "contact_name": lead.get("contact_name"),
                    "contact_title": lead.get("contact_title"),
                    "company_name": lead.get("company_name"),
                    "website": lead.get("website"),
                    "location": lead.get("location"),
                    "industry": niche,
                    "source": "linkedin",
                }
                
                score = scorer.score_lead(lead_dict)
                category = scorer.categorize_lead(score)
                lead_dict["score"] = score
                
                lead_id = await db.add_lead(lead_dict)
                await db.update_lead_status(lead_id, category)
                
                if lead.get("contact_name"):
                    await outbound.schedule_sequence(lead_id, "email")
                    await outbound.schedule_sequence(lead_id, "whatsapp")
                
                logger.info(f"LinkedIn lead: {lead.get('contact_name')} at {lead.get('company_name')}")
                total_found += 1
            
            await asyncio.sleep(5)
    
    return total_found


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


async def view_booking_pipeline(db):
    leads = await db.get_booking_pipeline()
    if not leads:
        print("No leads in booking pipeline yet.")
        return

    print("\nBooking Pipeline:")
    for lead in leads[:10]:
        _lid, company, contact, email, phone, status = lead[:6]
        print(f" - {company} ({contact or 'unknown'}) [{status}]")
        if email:
            print(f"   Email: {email}")
        if phone:
            print(f"   Phone: {phone}")
        del _lid  # explicitly mark intentionally unused


async def show_open_stats(db):
    rows = await db.get_open_stats_by_step()
    if not rows:
        print("No email opens tracked yet.")
        return
    print("\nEmail open rate by sequence step:")
    print(f"{'Step':<6}{'Sent':<8}{'Opened':<8}{'Open Rate':<10}")
    for step, sent, opened in rows:
        rate = f"{(opened / sent * 100):.1f}%" if sent else "0.0%"
        print(f"{step:<6}{sent:<8}{opened:<8}{rate:<10}")


async def send_daily_summary(db, whatsapp):
    summary = DailySummary(db, whatsapp if whatsapp.page else None)
    sent = await summary.run_and_send()
    if sent:
        print("Daily summary sent to owner via WhatsApp")
    else:
        print("Failed to send daily summary (check OWNER_PHONE and WhatsApp connection)")


async def schedule_daily_summary(db, whatsapp):
    while True:
        now = datetime.now()
        target = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now >= target:
            # timedelta handles month/year rollover; target.replace(day=day+1)
            # crashes on the last day of a month (e.g. day=31 in June).
            target = target + timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        await asyncio.sleep(wait_seconds)
        await send_daily_summary(db, whatsapp)


def build_components(db):
    """Construct the shared service objects used by both interactive and CLI modes."""
    ai = AIClient()
    whatsapp = WhatsAppBot()
    whatsapp.db = db
    whatsapp.ai = ai
    msg_gen = MessageGenerator(ai)
    # Single shared EmailSender so SMTP connections are reused across the
    # whole process and across OutreachSequence, EmailResponsePoller, and
    # booking outreach.  See code review B10.
    email_sender = EmailSender()
    return {
        "ai": ai,
        "scraper": LeadScraper(),
        "scorer": LeadScorer(),
        "msg_gen": msg_gen,
        "whatsapp": whatsapp,
        "analytics": Analytics(db),
        "outbound": OutreachSequence(db, msg_gen, whatsapp, email_sender=email_sender),
        "email_poller": EmailResponsePoller(db, ai, email_sender=email_sender),
        "email_sender": email_sender,
        "linkedin_scraper": LinkedInScraper(),
        # GLOBAL services
        "icp": ICPScorer(),
        "tz": TimezoneScheduler(),
        "lang": LangHandler(ai),
        "usage": APIUsageTracker(),
    }


async def run_once(mode: str):
    """Run a single action and exit — for cron / Task Scheduler automation."""
    db = LeadDatabase()
    await db.connect()
    await migrate()  # ensure global columns exist
    logger.info(f"Database connected (run-once mode: {mode})")

    tracking_server = TrackingServer(db, port=get_tracking_port())
    await tracking_server.start()

    c = build_components(db)
    try:
        if mode == "prospect":
            count = await run_prospecting(db, c)
            print(f"Found {count} prospects")
        elif mode == "linkedin":
            count = await run_linkedin_prospecting(
                db, c["scraper"], c["scorer"], c["linkedin_scraper"], c["outbound"]
            )
            print(f"Found {count} LinkedIn leads")
        elif mode == "outreach":
            sent = await run_outreach(db, c["outbound"], "email")
            print(f"Sent {sent} emails")
        elif mode == "whatsapp":
            sent = await run_outreach(db, c["outbound"], "whatsapp")
            print(f"Sent {sent} WhatsApp messages")
        elif mode == "responses":
            await check_email_responses(c["email_poller"])
        elif mode == "report":
            chart, stats = await c["analytics"].generate_daily_report()
            print(f"Report saved: {chart}")
            print(f"Stats: {stats}")
        else:
            print(f"Unknown mode: {mode}")
    except Exception as exc:
        logger.error(f"run-once ({mode}) failed: {exc}")
        print(f"Error: {exc}")
    finally:
        await tracking_server.stop()
        await c["email_sender"].close()
        await db.close()


async def main_loop():
    db = LeadDatabase()
    await db.connect()
    await migrate()  # ensure global columns exist
    logger.info("Database connected")

    tracking_server = TrackingServer(db, port=get_tracking_port())
    await tracking_server.start()

    c = build_components(db)
    scraper = c["scraper"]
    scorer = c["scorer"]
    whatsapp = c["whatsapp"]
    analytics = c["analytics"]
    outbound = c["outbound"]
    email_poller = c["email_poller"]
    linkedin_scraper = c["linkedin_scraper"]

    show_whatsapp_menu = False
    
    # Track background tasks for graceful shutdown.
    _background_tasks: set[asyncio.Task] = set()

    def _spawn(task_coro, *, name=None):
        """Spawn a background task and track it for cancellation on exit."""
        t = asyncio.create_task(task_coro, name=name)
        _background_tasks.add(t)
        t.add_done_callback(_background_tasks.discard)
        return t

    _spawn(schedule_daily_summary(db, whatsapp), name="schedule_daily_summary")

    for line in global_status_lines(c["usage"]):
        print(line)

    while True:
        print("\n=== Lead Gen Agent — GLOBAL MODE ===")
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
        print("10. Run LinkedIn prospecting")
        print("11. View email open stats")
        print("12. Send daily summary now")
        print("13. View booking pipeline")
        print("14. Exit")
        
        choice = input("Select option: ").strip()
        
        try:
            if choice == "1":
                count = await run_prospecting(db, c)
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
                        print(f" - {lead[1]} (Score: {lead[11] if len(lead) > 11 else 'N/A'})")
            
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
                        print(f" - Lead {m[1]}: Step {m[3] if len(m) > 3 else 'unknown'}")
            
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
                count = await run_linkedin_prospecting(db, scraper, scorer, linkedin_scraper, outbound)
                print(f"Found {count} LinkedIn leads")
            
            elif choice == "11":
                await show_open_stats(db)
            
            elif choice == "12":
                await send_daily_summary(db, whatsapp)
            
            elif choice == "13":
                await view_booking_pipeline(db)
            
            elif choice == "14":
                for t in _background_tasks:
                    t.cancel()
                await asyncio.gather(*_background_tasks, return_exceptions=True)
                await tracking_server.stop()
                await c["email_sender"].close()
                await db.close()
                break
        except Exception as exc:
            logger.error(f"Error: {exc}")
            print(f"Error: {exc}")


def parse_args(argv=None):
    import argparse
    parser = argparse.ArgumentParser(
        description="Lead Generation Agent. With no flags, launches the interactive menu. "
                    "A single mode flag runs that action once and exits (for cron / Task Scheduler)."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--prospect", action="store_const", const="prospect", dest="mode",
                       help="Run GLOBAL multi-source prospecting once and exit")
    group.add_argument("--linkedin", action="store_const", const="linkedin", dest="mode",
                       help="Run LinkedIn prospecting once and exit")
    group.add_argument("--outreach", action="store_const", const="outreach", dest="mode",
                       help="Send pending email outreach once and exit")
    group.add_argument("--whatsapp", action="store_const", const="whatsapp", dest="mode",
                       help="Send pending WhatsApp outreach once and exit")
    group.add_argument("--responses", action="store_const", const="responses", dest="mode",
                       help="Check & classify email replies once and exit")
    group.add_argument("--report", action="store_const", const="report", dest="mode",
                       help="Generate the analytics report once and exit")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    if args.mode:
        asyncio.run(run_once(args.mode))
    else:
        asyncio.run(main_loop())