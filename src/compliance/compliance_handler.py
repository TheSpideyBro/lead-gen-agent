"""CAN-SPAM / GDPR compliance layer for global outreach.

GLOBAL-specific: different regions impose different rules. This handler:
  - appends a compliant footer to every email (physical address, opt-out line,
    sender name + company; plus a GDPR data-processing notice when GDPR_MODE),
  - detects inbound opt-outs ("STOP", "unsubscribe", "remove me"),
  - maintains a global suppression list (global_unsubscribe table) checked before
    every send,
  - applies per-region sending rules from config/compliance_rules.json,
  - logs every send for an audit trail.
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("compliance.audit")

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
RULES_PATH = CONFIG_DIR / "compliance_rules.json"
PROFILE_PATH = CONFIG_DIR / "agency_profile.json"

OPTOUT_PHRASES = ("stop", "unsubscribe", "remove me", "opt out", "opt-out",
                  "no thanks", "leave me alone")


class ComplianceHandler:
    def __init__(self, db=None):
        self.db = db
        self.gdpr_mode = os.getenv("GDPR_MODE", "false").lower() == "true"
        self.rules = self._load_json(RULES_PATH).get("regions", {})
        self.profile = self._load_json(PROFILE_PATH)

    def _load_json(self, path: Path) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            logger.warning("compliance: could not read %s", path.name)
            return {}

    # ----- region resolution --------------------------------------------------

    def region_for_country(self, country_code: Optional[str]) -> str:
        if not country_code:
            return "default"
        code = country_code.strip().upper()
        for region, cfg in self.rules.items():
            if code in cfg.get("countries", []):
                return region
        return "default"

    def rules_for(self, country_code: Optional[str]) -> dict:
        region = self.region_for_country(country_code)
        return self.rules.get(region, self.rules.get("default", {}))

    # ----- outbound footer ----------------------------------------------------

    def build_footer(self, country_code: Optional[str] = None) -> str:
        name = self.profile.get("your_name", "")
        agency = self.profile.get("agency_name", "")
        address = self.profile.get("your_address", "")
        lines = ["", "--", f"{name}{', ' + agency if agency else ''}".strip(", ")]
        if address:
            lines.append(address)
        lines.append("Reply STOP to unsubscribe.")
        if self.gdpr_mode:
            lines.append(
                "You are receiving this because your business contact details are "
                "publicly available. We process this data under legitimate interest; "
                "reply STOP and we will erase your data and never contact you again.")
        return "\n".join(lines)

    # Patterns that indicate a proper opt-out footer is already present.
    # We check for these instead of a bare substring to avoid skipping the
    # footer when the word "unsubscribe" happens to appear in the body prose.
    FOOTER_PATTERNS = (
        "reply stop to unsubscribe",
        "unsubscribe link",
        "privacy policy",
        "opt-out",
        "can't reach you",
        "mailchimp",       # common ESP footers
        "sendgrid",
        "postmark",
    )

    def ensure_email_compliant(self, body: str, country_code: Optional[str] = None) -> str:
        """Append the compliant footer unless one is already present."""
        lower_body = (body or "").lower()
        if any(pat in lower_body for pat in self.FOOTER_PATTERNS):
            return body
        return f"{body}\n{self.build_footer(country_code)}"

    # ----- opt-out detection + suppression list -------------------------------

    @staticmethod
    def is_optout(text: str) -> bool:
        if not text:
            return False
        t = text.strip().lower()
        return any(p in t for p in OPTOUT_PHRASES)

    async def record_optout(self, email: str = None, phone: str = None, reason: str = "inbound opt-out"):
        if self.db:
            await self.db.add_unsubscribe(email=email, phone=phone, reason=reason)
        audit_logger.info("OPTOUT email=%s phone=%s reason=%s", email, phone, reason)

    async def is_suppressed(self, email: str = None, phone: str = None) -> bool:
        """Check the global suppression list before any send."""
        if not self.db:
            return False
        return await self.db.is_unsubscribed(email=email, phone=phone)

    # ----- audit trail --------------------------------------------------------

    def log_send(self, channel: str, recipient: str, lead_id=None, region: str = "default"):
        audit_logger.info(
            "SEND ts=%s channel=%s recipient=%s lead_id=%s region=%s",
            datetime.now(timezone.utc).isoformat(), channel, recipient, lead_id, region)
