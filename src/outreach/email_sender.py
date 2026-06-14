import asyncio
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from src.tracking.tracker import tracking_pixel_html
from src.utils.validators import validate_email, sanitize_string

logger = logging.getLogger(__name__)


class EmailSender:
    def __init__(self):
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.email_address = os.getenv("EMAIL_ADDRESS", "")
        self.email_password = os.getenv("EMAIL_PASSWORD", "")
        self.from_name = os.getenv("FROM_NAME", "Digital Marketing Expert")
        self._connection: Optional[smtplib.SMTP] = None
        # Serialize concurrent senders: a single smtplib.SMTP socket is not
        # safe to interleave sendmail() calls on. See code review B3.
        self._send_lock = asyncio.Lock()

    def can_send(self) -> bool:
        return bool(self.email_address and self.email_password)

    async def _connect(self) -> smtplib.SMTP:
        if self._connection is None:
            self._connection = await asyncio.to_thread(self._smtp_connect)
        return self._connection

    async def _disconnect(self):
        if self._connection:
            try:
                await asyncio.to_thread(self._connection.quit)
            except Exception:
                pass
            self._connection = None

    def _html_escape(self, text: str) -> str:
        """Minimal HTML escaping for embedding LLM output in email bodies.

        The LLM occasionally returns snippets that look like HTML; embedding
        them raw creates both rendering artifacts and a small XSS surface
        (the tracking pixel URL is the most worrying vector).
        """
        if not text:
            return ""
        # Build the entity strings at runtime so the diff tool doesn't
        # interpret them as HTML and strip them.
        amp = chr(38) + "amp;"
        lt = chr(38) + "lt;"
        gt = chr(38) + "gt;"
        quot = chr(38) + "quot;"
        return (
            text.replace(chr(38), amp)
                .replace(chr(60), lt)
                .replace(chr(62), gt)
                .replace(chr(34), quot)
        )

    async def send_email(self, to_email: str, subject: str, body: str,
                         lead_id: Optional[int] = None,
                         sequence_id: Optional[int] = None) -> bool:
        if not self.can_send():
            logger.warning("Email credentials not configured")
            return False

        if not validate_email(to_email):
            logger.warning(f"Invalid email address: {to_email}")
            return False

        to_email = sanitize_string(to_email)
        subject = sanitize_string(subject, 200)
        body = sanitize_string(body)

        msg = MIMEMultipart("alternative")
        msg["From"] = f"{self.from_name} <{self.email_address}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        if lead_id is not None and sequence_id is not None:
            pixel = tracking_pixel_html(lead_id, sequence_id)
            html_body = self._html_escape(body).replace("\n", "<br>\n")
            html = f"<html><body>{html_body}{pixel}</body></html>"
            msg.attach(MIMEText(html, "html"))

        # Serialize access to the SMTP socket. The lock is reentrant in the
        # sense that even a single coroutine that retries after a transport
        # error will not race with another caller.
        async with self._send_lock:
            try:
                server = await self._connect()
                await asyncio.to_thread(
                    server.sendmail,
                    self.email_address,
                    to_email,
                    msg.as_string()
                )
                logger.info("Email sent", extra={"to": to_email, "lead_id": lead_id})
                return True
            except Exception as exc:
                logger.error("Failed to send email: %s", exc, extra={"to": to_email})
                # Drop the broken connection so the next call re-handshakes.
                await self._disconnect()
                return False

    def _smtp_connect(self) -> smtplib.SMTP:
        server = smtplib.SMTP(self.smtp_server, self.smtp_port)
        server.starttls()
        server.login(self.email_address, self.email_password)
        return server

    async def close(self):
        await self._disconnect()


class LeadScorer:
    def __init__(self):
        self.high_value_industries = {"SaaS", "E-commerce", "Finance", "Healthcare"}
        self.medium_value_industries = {"Professional Services", "Education", "Real Estate"}

    def score_lead(self, lead: dict) -> int:
        score = 0

        industry = lead.get("industry") or ""
        if industry in self.high_value_industries:
            score += 30
        elif industry in self.medium_value_industries:
            score += 20
        else:
            score += 10

        employees = lead.get("employees") or 0
        if employees >= 100:
            score += 20
        elif employees >= 20:
            score += 15
        elif employees >= 5:
            score += 10

        if lead.get("email"):
            score += 20

        location = lead.get("location") or ""
        if any(loc in location for loc in ["US", "UK", "Canada", "Australia", "Germany", "UAE"]):
            score += 20

        website = lead.get("website")
        if website and "linkedin" not in website.lower():
            score += 10

        if lead.get("opened"):
            score += 15

        return score

    def categorize_lead(self, score: int) -> str:
        if score >= 60:
            return "hot"
        elif score >= 40:
            return "warm"
        else:
            return "cold"

    async def rescore_opened_lead(self, db, lead_id: int):
        lead = await db.get_lead_by_id(lead_id)
        if not lead:
            return
        lead["opened"] = True
        score = self.score_lead(lead)
        category = self.categorize_lead(score)
        await db.update_lead_score(lead_id, score)
        await db.update_lead_status(lead_id, category)