import imaplib
import email
import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Tuple

from src.outreach.email_sender import EmailSender

logger = logging.getLogger(__name__)


class EmailResponsePoller:
    def __init__(self, db, ai_client):
        self.db = db
        self.ai = ai_client
        self.email_address = os.getenv("EMAIL_ADDRESS", "")
        self.email_password = os.getenv("EMAIL_PASSWORD", "")
        self.imap_server = os.getenv("IMAP_SERVER", "imap.gmail.com")
        self.imap_port = int(os.getenv("IMAP_PORT", "993"))
        self.calendly_link = os.getenv("CALENDLY_LINK", "")
        self.from_name = os.getenv("FROM_NAME", "Digital Marketing Expert")

    def can_poll(self) -> bool:
        return bool(self.email_address and self.email_password)

    async def check_for_replies(self) -> int:
        if not self.can_poll():
            logger.warning("Email credentials not configured for IMAP")
            return 0

        try:
            leads = await self.db.get_all_leads_with_email()
            count = 0
            
            M = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            M.login(self.email_address, self.email_password)
            M.select("inbox")
            
            for lead_id, lead_email in leads:
                # Search for emails from this lead
                status, messages = M.search(None, f'FROM "{lead_email}"')
                for msg_id in messages[0].split():
                    status, msg_data = M.fetch(msg_id, "(RFC822)")
                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])
                            subject = msg["subject"] or ""
                            body = self._get_body(msg)
                            
                            # Skip if already processed (check by subject/body hash)
                            existing = await self.db.get_unreplied_responses()
                            if self._is_duplicate(subject, body, existing):
                                continue
                            
                            # Classify with AI
                            classification = await self._classify_reply(body)
                            await self.db.log_email_response(lead_id, subject, body, classification)
                            
                            # Handle classification
                            if classification == "interested":
                                await self._send_calendly(lead_email, lead_id)
                                await self.db.update_lead_status(lead_id, "qualified")
                                count += 1
                            elif classification == "not_interested":
                                await self.db.update_lead_status(lead_id, "unsubscribed")
                                await self.db.stop_all_sequences(lead_id)
                            elif classification == "out_of_office":
                                await self.db.reschedule_sequence(lead_id, 5)
                            elif classification == "question":
                                await self._send_answer(lead_email, lead_id, body)
            
            M.close()
            M.logout()
            return count
            
        except Exception as exc:
            logger.error(f"IMAP error: {exc}")
            return 0

    async def _classify_reply(self, body: str) -> str:
        prompt = f"""Classify this email reply as exactly one of: interested, not_interested, question, out_of_office.
        
Email body:
"{body[:500]}"

Respond with only the classification word."""
        result = await self.ai.generate(prompt, "You are an email classifier.")
        classification = result.strip().lower().split()[0] if result else "question"
        valid = {"interested", "not_interested", "question", "out_of_office"}
        return classification if classification in valid else "question"

    def _get_body(self, msg) -> str:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    return part.get_payload(decode=True).decode("utf-8", errors="ignore")
        return msg.get_payload(decode=True).decode("utf-8", errors="ignore")

    def _is_duplicate(self, subject: str, body: str, existing) -> bool:
        content = f"{subject}:{body[:100]}"
        return any(content in str(r) for r in existing)

    async def _send_calendly(self, to_email: str, lead_id: int):
        sender = EmailSender()
        if self.calendly_link:
            subject = "Quick Call to Discuss Your Marketing Needs"
            body = f"""Thanks for your interest! Let's schedule a quick 15-minute call to discuss how I can help grow your business.

{self.calendly_link}

Looking forward to connecting!"""
            await sender.send_email(to_email, subject, body)
            await sender.close()

    async def _send_answer(self, to_email: str, lead_id: int, question: str):
        sender = EmailSender()
        lead = await self.db.get_lead_by_id(lead_id)
        
        prompt = f"""Answer this prospect question briefly and helpfully:

Question: "{question}"

Keep under 100 words, sign off with your name."""
        answer = await self.ai.generate(prompt, "You are a helpful sales rep.")
        await sender.send_email(to_email, "Re: Your Question", answer)
        await sender.close()

    async def get_pending_responses(self):
        return await self.db.get_unreplied_responses()