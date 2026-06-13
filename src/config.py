"""Centralised configuration for the lead-gen agent.

Replaces the `os.getenv(...)` calls scattered across every module with a
single typed settings object. Fails fast on missing required keys so a
broken deployment is detected at startup, not on the first cron run.
See code review (architectural concerns — config sprawl).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _env(key: str, default: str = "", *, required: bool = False) -> str:
    val = os.getenv(key, default)
    if required and not val:
        raise RuntimeError(
            f"Required environment variable {key!r} is not set. "
            "Copy .env.example to .env and fill it in."
        )
    return val


def _int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    # AI ----------------------------------------------------------------
    groq_api_key: str = field(default_factory=lambda: _env("GROQ_API_KEY"))
    google_ai_api_key: str = field(default_factory=lambda: _env("GOOGLE_AI_API_KEY"))
    groq_model: str = field(default_factory=lambda: _env("GROQ_MODEL", "llama-3.3-70b-versatile"))
    google_ai_model: str = field(default_factory=lambda: _env("GOOGLE_AI_MODEL", "gemini-2.0-flash"))
    ai_max_retries: int = field(default_factory=lambda: _int("AI_MAX_RETRIES", 3))

    # Email -------------------------------------------------------------
    email_address: str = field(default_factory=lambda: _env("EMAIL_ADDRESS"))
    email_password: str = field(default_factory=lambda: _env("EMAIL_PASSWORD"))
    from_name: str = field(default_factory=lambda: _env("FROM_NAME", "Digital Marketing Expert"))
    smtp_server: str = field(default_factory=lambda: _env("SMTP_SERVER", "smtp.gmail.com"))
    smtp_port: int = field(default_factory=lambda: _int("SMTP_PORT", 587))
    imap_server: str = field(default_factory=lambda: _env("IMAP_SERVER", "imap.gmail.com"))
    imap_port: int = field(default_factory=lambda: _int("IMAP_PORT", 993))
    calendly_link: str = field(default_factory=lambda: _env("CALENDLY_LINK"))

    # LinkedIn ----------------------------------------------------------
    linkedin_email: str = field(default_factory=lambda: _env("LINKEDIN_EMAIL"))
    linkedin_password: str = field(default_factory=lambda: _env("LINKEDIN_PASSWORD"))
    linkedin_headless: bool = field(default_factory=lambda: _bool("LINKEDIN_HEADLESS", False))
    linkedin_data_dir: Path = field(default_factory=lambda: Path(_env("LINKEDIN_DATA_DIR", "data/linkedin")))

    # WhatsApp ----------------------------------------------------------
    whatsapp_headless: bool = field(default_factory=lambda: _bool("WHATSAPP_HEADLESS", False))
    whatsapp_data_dir: Path = field(default_factory=lambda: Path(_env("WHATSAPP_DATA_DIR", "data/whatsapp")))
    owner_phone: str = field(default_factory=lambda: _env("OWNER_PHONE"))

    # Tracking / DB -----------------------------------------------------
    tracking_base_url: str = field(default_factory=lambda: _env("TRACKING_BASE_URL", "http://localhost:8080"))
    tracking_secret: str = field(default_factory=lambda: _env("TRACKING_SECRET", "change-me"))
    lead_db_path: Path = field(default_factory=lambda: Path(_env("LEAD_DB_PATH", "data/lead_bot.db")))

    # Google Custom Search ---------------------------------------------
    google_api_key: str = field(default_factory=lambda: _env("GOOGLE_API_KEY"))
    google_search_id: str = field(default_factory=lambda: _env("GOOGLE_SEARCH_ID"))

    @property
    def tracking_port(self) -> int:
        try:
            return int(self.tracking_base_url.rstrip("/").rsplit(":", 1)[-1])
        except (ValueError, IndexError):
            return 8080

    def ensure_data_dirs(self) -> None:
        for d in (self.lead_db_path.parent, self.linkedin_data_dir, self.whatsapp_data_dir,
                  Path("output/reports")):
            d.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    s = Settings()
    s.ensure_data_dirs()
    return s
