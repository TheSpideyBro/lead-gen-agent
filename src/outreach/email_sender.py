import asyncio
import logging
import os
import smtplib
from contextlib import contextmanager
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

logger = logging.getLogger(__name__)


class EmailSender:
    _instance: Optional["EmailSender"] = None
    _server = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.email_address = os.getenv("EMAIL_ADDRESS", "")
        self.email_password = os.getenv("EMAIL_PASSWORD", "")
        self.from_name = os.getenv("FROM_NAME", "Digital Marketing Expert")
        self._initialized = True

    def can_send(self) -> bool:
        return bool(self.email_address and self.email_password)

    async def _connect(self):
        if self._server is None:
            self._server = await asyncio.to_thread(self._smtp_connect)
        return self._server

    async def _disconnect(self):
        if self._server:
            try:
                await asyncio.to_thread(self._server.quit)
            except Exception:
                pass
            self._server = None

    async def send_email(self, to_email: str, subject: str, body: str) -> bool:
        if not self.can_send():
            logger.warning("Email credentials not configured")
            return False

        msg = MIMEMultipart()
        msg["From"] = f"{self.from_name} <{self.email_address}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        try:
            server = await self._connect()
            await asyncio.to_thread(
                server.sendmail,
                self.email_address,
                to_email,
                msg.as_string()
            )
            logger.info(f"Email sent to {to_email}")
            return True
        except Exception as exc:
            logger.error(f"Failed to send email: {exc}")
            self._server = None  # Reset on error
            return False

    def _smtp_connect(self):
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

        industry = lead.get("industry", "")
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

        location = lead.get("location", "")
        if any(loc in location for loc in ["US", "UK", "Canada", "Australia", "Germany", "UAE"]):
            score += 20

        website = lead.get("website")
        if website and "linkedin" not in website.lower():
            score += 10

        return score

    def categorize_lead(self, score: int) -> str:
        if score >= 60:
            return "hot"
        elif score >= 40:
            return "warm"
        else:
            return "cold"