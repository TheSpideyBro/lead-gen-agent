import hashlib
import imaplib
import email
import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any

from src.outreach.email_sender import EmailSender

logger = logging.getLogger(__name__)


class EmailResponsePoller:
    # Canonical classification vocabulary — keep in sync with daily_summary.
    VALID_CLASSIFICATIONS = {"interested", "not_interested", "question", "out_of_office"}

    def __init__(self, db, ai_client, email_sender=None):
        self.db = db
        self.ai = ai_client
        self.email_sender = email_sender or EmailSender()
        self.email_address = os.getenv("EMAIL_ADDRESS", "")
        self.email_password = os.getenv("EMAIL_PASSWORD", "")
        self.imap_server = os.getenv("IMAP_SERVER", "imap.gmail.com")
        self.imap_port = int(os.getenv("IMAP_PORT", "993"))
        self.calendly_link = os.getenv("CALENDLY_LINK", "")
        self.from_name = os.getenv("FROM_NAME", "Digital Marketing Expert")
        self._processed_messages: set = set()

    def can_poll(self) -> bool:
        return bool(self.email_address and self.email_password)

    async def check_for_replies(self) -> int:
        if not self.can_poll():
            logger.warning("Email credentials not configured for IMAP")
            return 0

        M = None
        try:
            leads = await self.db.get_all_leads_with_email()
            count = 0

            M = await asyncio.to_thread(
                imaplib.IMAP4_SSL, self.imap_server, self.imap_port
            )
            await asyncio.to_thread(M.login, self.email_address, self.email_password)
            await asyncio.to_thread(M.select, "inbox")

            for lead_id, lead_email in leads:
                message_ids = await self._search_messages(M, lead_email)
                for msg_id in message_ids:
                    msg_hash = hashlib.md5(f"{msg_id}:{lead_id}".encode()).hexdigest()
                    if msg_hash in self._processed_messages:
                        continue

                    msg_data = await self._fetch_message(M, msg_id)
                    if not msg_data:
                        continue

                    subject, body = self._parse_message(msg_data)
                    classification = await self._classify_reply(body)
                    await self.db.log_email_response(lead_id, subject, body, classification)
                    self._processed_messages.add(msg_hash)

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

            return count

        except Exception as exc:
            # Don't echo the raw exception — imaplib includes the failing
            # search command, which leaks recipient addresses.  See review S5.
            logger.error("IMAP polling failed: %s", type(exc).__name__)
            return 0
        finally:
            if M is not None:
                # Best-effort close: never let an exception strand an open
                # IMAP connection.  See review B4.
                try:
                    await asyncio.to_thread(M.close)
                except Exception:
                    pass
                try:
                    await asyncio.to_thread(M.logout)
                except Exception:
                    pass

    async def _search_messages(self, M, lead_email: str) -> list:
        # RFC 3501 — FROM takes a quoted *display name*; to filter by address
        # we wrap the address in angle brackets and use the address atom.  See
        # code review B5.  The previous `FROM "{email}"` form returned zero
        # results on Gmail/Outlook because they interpret it as a display name.
        from email.utils import parseaddr

        today = datetime.now().strftime("%d-%b-%Y")
        # Sanitize: never put the raw user input inside a quoted-string.
        safe_email = lead_email.replace("\\", "").replace('"', "")
        criteria = f'(FROM "<{safe_email}>") SINCE {today}'
        try:
            status, messages = await asyncio.to_thread(M.search, None, criteria)
        except Exception as exc:
            logger.warning(
                "IMAP search with addr atom failed (%s); retrying plain",
                type(exc).__name__,
            )
            criteria = f'FROM "{safe_email}" SINCE {today}'
            status, messages = await asyncio.to_thread(M.search, None, criteria)
        if status != "OK":
            return []
        return messages[0].split() if messages and messages[0] else []

    async def _fetch_message(self, M, msg_id) -> Optional[bytes]:
        status, msg_data = await asyncio.to_thread(M.fetch, msg_id, "(RFC822)")
        return msg_data

    def _parse_message(self, msg_data) -> Tuple[str, str]:
        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                subject = msg["subject"] or ""
                body = self._get_body(msg)
                return subject, body
        return "", ""

    def _get_body(self, msg) -> str:
        # Use errors="replace" rather than errors="ignore" so a mis-encoded
        # message surfaces in the logs instead of being silently corrupted —
        # corruption here is what causes the AI classifier to label "STOP" as
        # "interested".  See code review S6.
        def _decode(payload: bytes) -> str:
            if not payload:
                return ""
            try:
                return payload.decode("utf-8")
            except UnicodeDecodeError:
                return payload.decode("utf-8", errors="replace")

        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    return _decode(part.get_payload(decode=True))
        return _decode(msg.get_payload(decode=True))

    async def _classify_reply(self, body: str) -> str:
        prompt = f"""Classify this email reply as exactly one of: interested, not_interested, question, out_of_office.

Email body:
"{body[:500]}"

Respond with only the classification word."""
        result = await self.ai.generate(prompt, "You are an email classifier.")
        classification = result.strip().lower().split()[0] if result else "question"
        return classification if classification in self.VALID_CLASSIFICATIONS else "question"

    async def _send_calendly(self, to_email: str, lead_id: int):
        if not self.calendly_link:
            return
        subject = "Quick Call to Discuss Your Marketing Needs"
        body = f"""Thanks for your interest! Let's schedule a quick 15-minute call to discuss how I can help grow your business.

{self.calendly_link}

Looking forward to connecting!"""
        await self.email_sender.send_email(to_email, subject, body)

    async def _send_answer(self, to_email: str, lead_id: int, question: str):
        lead = await self.db.get_lead_by_id(lead_id)

        prompt = f"""Answer this prospect question briefly and helpfully:

Question: "{question}"

Keep under 100 words, sign off with your name."""
        answer = await self.ai.generate(prompt, "You are a helpful sales rep.")
        await self.email_sender.send_email(to_email, "Re: Your Question", answer)

    async def get_pending_responses(self):
        return await self.db.get_unreplied_responses()