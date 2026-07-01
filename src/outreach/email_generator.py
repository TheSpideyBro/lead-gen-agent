import asyncio
import json
import logging
from src.ai_client import AIClient
from src.outreach.email_sender import EmailSender
from src.scheduling.timezone_scheduler import TimezoneScheduler
from src.language.lang_handler import LangHandler
from src.compliance.compliance_handler import ComplianceHandler

logger = logging.getLogger(__name__)


# Terminal statuses a lead should never be moved out of by booking outreach.
# Once a lead has qualified, been sent a booking link, or unsubscribed, the
# booking flow must not clobber that state.  See refactor-agent code review
# B11.
_BOOKING_GUARD = {"qualified", "booking_sent", "unsubscribed"}


class MessageGenerator:
    def __init__(self, ai_client: AIClient, profile_path: str = "config/agency_profile.json"):
        self.ai = ai_client
        self.profile = self._load_profile(profile_path)

    def _signature(self) -> str:
        """Render the email signature safely.

        The previous code used str.format() directly, which raised KeyError
        if the signature contained a literal `{`. We use str.replace() with
        two positional placeholders instead, and tolerate a missing/empty
        signature.  See refactor-agent code review (v1.4.0 P1).
        """
        template = self.profile.get("email_signature", "") or ""
        email = self.profile.get("your_email", "") or ""
        phone = self.profile.get("your_phone", "") or ""
        return template.replace("{email}", email).replace("{phone}", phone)

    def _load_profile(self, path: str) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.error(f"Failed to load agency profile: {exc}")
            return {}

    async def generate_initial_message(self, lead: dict, channel: str = "email") -> tuple:
        system_prompt = f"""You are {self.profile.get('your_name', 'a sales representative')} from {self.profile.get('agency_name', 'a digital marketing agency')}. 
        Write a personalized {channel} message to a prospect at {lead.get('company_name', 'their company')}.
        Keep it short, value-focused, and mention specific pain points."""
        
        if channel == "whatsapp":
            user_prompt = f"""Generate a WhatsApp cold message (under 200 words) for:
            
            Company: {lead.get('company_name')}
            Industry: {lead.get('industry')}
            Contact: {lead.get('contact_name', 'Decision Maker')}
            
            Services: {', '.join(self.profile.get('services', []))}
            Pain points: {', '.join(self.profile.get('target_client_profile', {}).get('pain_points', []))}
            
            Be direct, friendly, no subject line needed. End with call-to-action."""
        else:
            user_prompt = f"""Generate a cold outreach email for:
            
            Company: {lead.get('company_name')}
            Industry: {lead.get('industry')}
            Contact: {lead.get('contact_name', 'Decision Maker')}
            Location: {lead.get('location')}
            
            My services: {', '.join(self.profile.get('services', []))}
            Key pain points to address: {', '.join(self.profile.get('target_client_profile', {}).get('pain_points', []))}
            
            Include:
            - Personalized hook
            - Specific value proposition
            - Case study brief (25% traffic increase for similar biz)
            - Clear CTA for a 15-min call"""

        body = await self.ai.generate(user_prompt, system_prompt)
        
        if channel == "email":
            subject = f"Quick question about growing {lead.get('company_name', 'your business')}"
            full_body = f"{body}\n\n{self._signature()}"
            return subject, full_body
        
        return "", body

    async def generate_followup(self, lead: dict, step: int, channel: str = "email") -> tuple:
        followup_types = {
            1: "gentle reminder",
            2: "value addition (case study)",
            3: "final attempt with urgency"
        }
        
        system_prompt = f"You are {self.profile.get('your_name')} following up. Be concise and add value."
        
        case_study = self.profile.get("case_studies", [{}])[0].get("results", "")
        extra1 = f"Include a case study: {case_study}" if step == 2 else ""
        extra2 = "Ask directly if they are interested before closing." if step == 3 else ""
        extra3 = "Keep under 150 words." if channel == "whatsapp" else ""
        
        user_prompt = f"""Write a follow-up {channel} message (step {step}: {followup_types.get(step, 'follow-up')}) to {lead.get('contact_name', 'them')} at {lead.get('company_name')}.
        
        Reference previous outreach briefly.
        {extra1}
        {extra2}
        {extra3}"""

        body = await self.ai.generate(user_prompt, system_prompt)
        
        if channel == "email":
            subject = f"Re: {lead.get('company_name', 'your business')} growth opportunity"
            return subject, f"{body}\n\n{self._signature()}"
        
        return "", body


class OutreachSequence:
    SEQUENCES = {
        "email": [
            {"delay_hours": 0, "step": 1},
            {"delay_hours": 48, "step": 2},
            {"delay_hours": 96, "step": 3},
        ],
        "whatsapp": [
            {"delay_hours": 0, "step": 1},
            {"delay_hours": 24, "step": 2},
            {"delay_hours": 72, "step": 3},
        ]
    }

    # Minimum day gaps between steps; the timezone scheduler then snaps each to
    # the next optimal local send window (replaces the fixed hour delays above).
    STEP_GAPS_DAYS = {
        "email": [0, 2, 2],     # immediate, +2d, +2d
        "whatsapp": [0, 1, 2],  # immediate, +1d, +2d
    }

    def __init__(self, db, message_gen: MessageGenerator, whatsapp_bot=None, email_sender=None):
        self.db = db
        self.msg_gen = message_gen
        self.whatsapp = whatsapp_bot
        # GLOBAL additions: timezone-aware scheduling, localization, compliance.
        self.scheduler = TimezoneScheduler()
        self.lang = LangHandler(getattr(message_gen, "ai", None))
        self.compliance = ComplianceHandler(db)
        # Reuse a single EmailSender across the process so we don't open 30
        # SMTP connections when 30 hot leads are booked.  See refactor-agent
        # code review B10.
        self.email_sender = email_sender or EmailSender()

    async def schedule_sequence(self, lead_id: int, channel: str = "email"):
        """Schedule each step in the RECIPIENT's local optimal window.

        GLOBAL-specific: resolves the lead's timezone (stored or detected from
        country), then asks TimezoneScheduler for holiday-aware, weekday-aware
        slots instead of blindly adding fixed hours in server time.

        Refactor-agent B11-related fix: only schedule if the lead actually has
        a contact endpoint for this channel. The pre-global code scheduled an
        email sequence for a lead with no email and a WhatsApp sequence for a
        lead with no phone, wasting LLM calls and confusing the daily summary.
        """
        lead = await self.db.get_lead_by_id(lead_id) or {}
        if channel == "email" and not lead.get("email"):
            return
        if channel == "whatsapp" and not lead.get("phone"):
            return
        country = lead.get("country") or lead.get("location")
        tz_name = lead.get("detected_timezone") or self.scheduler.detect_timezone(country)
        country_code = self.scheduler.country_to_code(country)

        gaps = self.STEP_GAPS_DAYS.get(channel, self.STEP_GAPS_DAYS["email"])
        for step, when in self.scheduler.schedule_steps(tz_name, channel, gaps, country_code):
            await self.db.schedule_message(lead_id, channel, step, when)

    async def process_pending_emails(self, sender) -> int:
        pending = await self.db.get_pending_emails()
        sent_count = 0
        for seq_id, lead_id, step, email, name, company in pending:
            # Section 6: never contact a globally-suppressed address.
            if await self.compliance.is_suppressed(email=email):
                logger.info("Skipping suppressed email %s", email)
                await self.db.mark_email_sent(seq_id)
                continue
            lead = await self.db.get_lead_by_id(lead_id)
            if step == 1:
                subject, body = await self.msg_gen.generate_initial_message(lead, "email")
            else:
                subject, body = await self.msg_gen.generate_followup(lead, step, "email")
            # Localize subject + body to the recipient's language (Section 5).
            country = (lead or {}).get("country") or (lead or {}).get("location")
            country_code = self.scheduler.country_to_code(country)
            subject, _ = await self.lang.localize(subject, country)
            body, _ = await self.lang.localize(body, country)
            # Append compliant footer (physical address + opt-out + GDPR notice).
            body = self.compliance.ensure_email_compliant(body, country_code)
            # B3: atomic claim — if another process stole this row, skip it.
            if not await self.db.claim_sequence_for_send(seq_id):
                logger.debug("Sequence %d already claimed by another process", seq_id)
                continue
            try:
                await sender.send_email(email, subject, body, lead_id=lead_id, sequence_id=seq_id)
                self.compliance.log_send("email", email, lead_id,
                                         self.compliance.region_for_country(country_code))
                # B2: atomic log + mark in one transaction.
                await self.db.log_outreach_and_mark_sent(lead_id, "email", subject, body, seq_id)
                sent_count += 1
            except Exception as exc:
                # Send failed — undo the claim so another process can retry.
                logger.error("Email send failed for seq %d: %s — resetting claim", seq_id, exc)
                await self.db.db.execute(
                    "UPDATE sequences SET sent = 0 WHERE id = ?", (seq_id,))
                await self.db.db.commit()
            await asyncio.sleep(2)  # Rate limit
        return sent_count

    async def process_pending_whatsapp(self) -> int:
        pending = await self.db.get_pending_messages()
        sent_count = 0
        for seq_id, lead_id, channel, step, phone, name, company in pending:
            if channel == "whatsapp":
                # Section 6: respect global suppression list.
                if await self.compliance.is_suppressed(phone=phone):
                    await self.db.mark_message_sent(seq_id)
                    continue
                lead = await self.db.get_lead_by_id(lead_id)
                if step == 1:
                    _, body = await self.msg_gen.generate_initial_message(lead, "whatsapp")
                else:
                    _, body = await self.msg_gen.generate_followup(lead, step, "whatsapp")
                # Localize WhatsApp body to recipient's language (Section 5).
                country = (lead or {}).get("country") or (lead or {}).get("location")
                body, _ = await self.lang.localize(body, country)
                if self.whatsapp:
                    await self.whatsapp.send_message(phone, body)
                await self.db.log_outreach(lead_id, "whatsapp", "", body)
                await self.db.mark_message_sent(seq_id)
                sent_count += 1
                await asyncio.sleep(2)  # Rate limit
        return sent_count

    async def send_booking_outreach(self, lead: dict, channel: str = "email"):
        import os
        calendly_link = os.getenv("CALENDLY_LINK", "")
        
        if not calendly_link:
            logger.warning("CALENDLY_LINK not configured")
            return False
        
        lead_id = lead.get("id")
        if lead_id is None:
            logger.warning("send_booking_outreach called without a lead id")
            return False

        # B11 fix: don't downgrade a lead that already qualified / is in
        # the booking pipeline / has unsubscribed.
        current = (await self.db.get_lead_by_id(lead_id) or {}).get("status")
        if current in _BOOKING_GUARD:
            logger.info(
                "Skipping booking outreach: lead %s already %s",
                lead_id, current,
            )
            return False

        if channel == "email":
            subject = f"Quick 15-min call — {lead.get('company_name', 'your company')}?"
            body = await self._generate_booking_email(lead, calendly_link)
            # B10 fix: reuse the singleton EmailSender instead of opening
            # a fresh SMTP connection per booking outreach.
            success = await self.email_sender.send_email(
                lead.get("email"), subject, body, lead_id=lead_id, sequence_id=None
            )
            if success:
                await self.db.log_outreach(lead_id, "booking", subject, body)
                await self.db.update_lead_status(lead_id, "booking_sent")
            return success
        elif channel == "whatsapp":
            body = await self._generate_booking_whatsapp(lead, calendly_link)
            if self.whatsapp and self.whatsapp.page:
                phone = lead.get("phone", "")
                if phone:
                    await self.whatsapp.send_message(phone, body)
                    await self.db.log_outreach(lead_id, "booking", "", body)
                    await self.db.update_lead_status(lead_id, "booking_sent")
                    return True
        return False

    async def _generate_booking_email(self, lead: dict, calendly_link: str) -> str:
        system_prompt = f"You are {self.msg_gen.profile.get('your_name', 'a sales rep')} from {self.msg_gen.profile.get('agency_name', 'a digital marketing agency')}."
        user_prompt = f"""Write a short booking email to {lead.get('contact_name', 'them')} at {lead.get('company_name')}.
        
        They're a hot lead. Offer a 15-min call to discuss growth opportunities.
        
        Include:
        - Brief personalized hook
        - Value: {', '.join(self.msg_gen.profile.get('services', [])[:2])}
        - Calendly link: {calendly_link}
        
        Sign off professionally."""
        body = await self.msg_gen.ai.generate(user_prompt, system_prompt)
        return f"{body}\n\n{self.msg_gen._signature()}"

    async def _generate_booking_whatsapp(self, lead: dict, calendly_link: str) -> str:
        system_prompt = f"You are {self.msg_gen.profile.get('your_name', 'a sales rep')}."
        user_prompt = f"""Generate WhatsApp booking message (UNDER 100 WORDS) to {lead.get('contact_name', 'them')} at {lead.get('company_name')}.
        
        Hot lead - send Calendly link for quick call:
        {calendly_link}
        
        Be direct, friendly, under 100 words."""
        return await self.msg_gen.ai.generate(user_prompt, system_prompt)