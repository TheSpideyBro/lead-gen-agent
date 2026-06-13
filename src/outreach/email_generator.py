import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List
from src.ai_client import AIClient
from src.outreach.email_sender import EmailSender

logger = logging.getLogger(__name__)


class MessageGenerator:
    def __init__(self, ai_client: AIClient, profile_path: str = "config/agency_profile.json"):
        self.ai = ai_client
        self.profile = self._load_profile(profile_path)

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
            signature = self.profile.get('email_signature', '').format(
                email=self.profile.get('your_email', ''),
                phone=self.profile.get('your_phone', '')
            )
            full_body = f"{body}\n\n{signature}"
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
            signature = self.profile.get('email_signature', '').format(
                email=self.profile.get('your_email', ''),
                phone=self.profile.get('your_phone', '')
            )
            return subject, f"{body}\n\n{signature}"
        
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

    def __init__(self, db, message_gen: MessageGenerator, whatsapp_bot=None):
        self.db = db
        self.msg_gen = message_gen
        self.whatsapp = whatsapp_bot

    async def schedule_sequence(self, lead_id: int, channel: str = "email"):
        for config in self.SEQUENCES.get(channel, self.SEQUENCES["email"]):
            scheduled = datetime.now() + timedelta(hours=config["delay_hours"])
            await self.db.schedule_message(lead_id, channel, config["step"], scheduled.isoformat())

    async def process_pending_emails(self, sender) -> int:
        pending = await self.db.get_pending_emails()
        sent_count = 0
        for seq_id, lead_id, step, email, name, company in pending:
            lead = await self.db.get_lead_by_id(lead_id)
            if step == 1:
                subject, body = await self.msg_gen.generate_initial_message(lead, "email")
            else:
                subject, body = await self.msg_gen.generate_followup(lead, step, "email")
            await sender.send_email(email, subject, body, lead_id=lead_id, sequence_id=seq_id)
            await self.db.log_outreach(lead_id, "email", subject, body)
            await self.db.mark_email_sent(seq_id)
            sent_count += 1
            await asyncio.sleep(2)  # Rate limit
        return sent_count

    async def process_pending_whatsapp(self) -> int:
        pending = await self.db.get_pending_messages()
        sent_count = 0
        for seq_id, lead_id, channel, step, phone, name, company in pending:
            if channel == "whatsapp":
                lead = await self.db.get_lead_by_id(lead_id)
                if step == 1:
                    _, body = await self.msg_gen.generate_initial_message(lead, "whatsapp")
                else:
                    _, body = await self.msg_gen.generate_followup(lead, step, "whatsapp")
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
        
        if channel == "email":
            subject = f"Quick 15-min call — {lead.get('company_name', 'your company')}?"
            body = await self._generate_booking_email(lead, calendly_link)
            sender = EmailSender()
            success = await sender.send_email(
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
        signature = self.msg_gen.profile.get('email_signature', '').format(
            email=self.msg_gen.profile.get('your_email', ''),
            phone=self.msg_gen.profile.get('your_phone', '')
        )
        return f"{body}\n\n{signature}"

    async def _generate_booking_whatsapp(self, lead: dict, calendly_link: str) -> str:
        system_prompt = f"You are {self.msg_gen.profile.get('your_name', 'a sales rep')}."
        user_prompt = f"""Generate WhatsApp booking message (UNDER 100 WORDS) to {lead.get('contact_name', 'them')} at {lead.get('company_name')}.
        
        Hot lead - send Calendly link for quick call:
        {calendly_link}
        
        Be direct, friendly, under 100 words."""
        return await self.msg_gen.ai.generate(user_prompt, system_prompt)