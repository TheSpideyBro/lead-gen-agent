# Lead Generation Agent

> **AI-Powered Outbound Sales Automation** — Prospect discovery, lead scoring, multi-channel outreach (Email + WhatsApp + LinkedIn), and intelligent reply handling, all orchestrated by LLMs.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![asyncio](https://img.shields.io/badge/async-asyncio-green.svg)](https://docs.python.org/3/library/asyncio.html)
[![Tests](https://img.shields.io/badge/tests-13%20passed-brightgreen.svg)](tests/)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey.svg)](LICENSE)
[![Contributions Welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg)](CONTRIBUTING.md)

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Usage](#usage)
- [Autonomous Mode](#autonomous-mode)
- [Development](#development)
- [Testing](#testing)
- [Security](#security)
- [Compliance](#compliance)
- [Roadmap](#roadmap)
- [License](#license)

---

## Overview

Lead Generation Agent is a standalone command-line tool that runs an end-to-end outbound sales pipeline. It discovers prospects from multiple sources, scores them by fit, generates personalized multi-step outreach with an LLM, sends messages over email and WhatsApp, and classifies inbound replies to auto-respond, qualify, or unsubscribe leads — all from a single CLI or a 24/7 autonomous supervisor.

Built on `asyncio` for concurrent I/O, with a local SQLite database and pluggable AI providers (Groq primary, Google Gemini fallback).

---

## Features

| Category | Feature | Details |
|----------|---------|---------|
| **Discovery** | Multi-source prospecting | DuckDuckGo, Google Custom Search, Apollo.io, GitHub, ProductHunt, LinkedIn |
| **Scoring** | ICP scoring | Weighted scoring on title, funding, employees, signals → Hot/Warm/Cold tiers |
| **Outreach** | Email sequences | 3-step nurture cadence with AI-generated personalized copy |
| **Outreach** | WhatsApp messages | Playwright-based bot or 360dialog WhatsApp Business API |
| **Outreach** | Booking automation | Instant Calendly link delivery for hot leads |
| **Intelligence** | Reply classification | AI-powered classification (interested, question, opt-out, OOO, etc.) |
| **Intelligence** | Auto-responses | Qualify interested leads, answer questions, unsubscribe opt-outs |
| **Scheduling** | Timezone-aware | Schedules sends in recipient's local optimal windows |
| **Scheduling** | Holiday-aware | Skips national holidays per recipient country |
| **Localization** | Multi-language | AI-translates messages to recipient's language |
| **Compliance** | CAN-SPAM / GDPR | Physical address footers, opt-out detection, global suppression list |
| **Tracking** | Email opens | HMAC-signed tracking pixels with per-IP rate limiting |
| **Reporting** | Daily summaries | Automated pipeline stats delivered via WhatsApp |
| **Reporting** | Analytics | Matplotlib dashboards for outreach performance |
| **Autonomy** | 24/7 supervisor | Self-scheduling tasks, health monitoring, crash recovery, remote control |
| **Security** | Webhook auth | Meta challenge verification + HMAC signature verification |
| **Reliability** | Atomic sends | Database-level dedup prevents duplicate outreach |
| **Reliability** | Proxy rotation | Configurable proxy list for scraping resilience |

---

## Architecture

```
lead-gen-agent/
├── main.py                       # CLI entry point and interactive menu
├── agent.py                      # Autonomous 24/7 supervisor
├── connect_whatsapp.py           # One-time WhatsApp Web QR setup
├── pyproject.toml                # Project metadata & dependencies
├── requirements.txt              # Dependency ranges
├── .env.example                  # Environment variable template
├── config/
│   ├── agency_profile.json       # Agency info, services, ICP, case studies
│   ├── prospect_preferences.json # Search keywords, limits, working hours
│   ├── compliance_rules.json     # Per-region sending rules (GDPR, CAN-SPAM)
│   ├── global_holidays.json      # National holidays by country code
│   ├── global_targeting.json     # Firmographic targeting criteria
│   └── whatsapp_templates.json   # Pre-written WhatsApp message templates
├── src/
│   ├── database.py               # Async SQLite data layer (10 tables)
│   ├── ai_client.py              # Multi-provider LLM client (Groq / Gemini)
│   ├── analytics.py              # Stats aggregation + matplotlib reports
│   ├── config.py                 # Typed Settings dataclass + env loader
│   ├── logging_setup.py          # JSON/console formatter, rotating file handler
│   ├── compliance/
│   │   └── compliance_handler.py  # Footer builder, opt-out detection, suppression
│   ├── language/
│   │   └── lang_handler.py        # AI-assisted message localization
│   ├── outreach/
│   │   ├── email_sender.py        # SMTP sender with concurrency safety
│   │   ├── email_generator.py     # Message generation + sequence scheduler
│   │   └── email_response_handler.py  # IMAP polling + reply classification
│   ├── reports/
│   │   └── daily_summary.py       # Pipeline stats aggregation
│   ├── scheduling/
│   │   └── timezone_scheduler.py  # Holiday-aware optimal send slot calculator
│   ├── scoring/
│   │   └── icp_scorer.py          # Ideal Customer Profile scoring engine
│   ├── scrapers/
│   │   ├── prospect_scraper.py    # DuckDuckGo / Google search + email extraction
│   │   ├── apollo_scraper.py      # Apollo.io firmographic search
│   │   ├── github_scraper.py      # GitHub technical founder search
│   │   ├── producthunt_scraper.py # ProductHunt active launcher search
│   │   └── linkedin_scraper.py    # Playwright LinkedIn / Sales Navigator scraper
│   ├── tracking/
│   │   ├── tracker.py             # HMAC-signed tracking pixel URL generator
│   │   └── server.py              # aiohttp tracking pixel receiver
│   ├── utils/
│   │   ├── validators.py          # Email/phone validation, sanitization, normalization
│   │   ├── rate_limiter.py        # Retry + backoff utilities
│   │   ├── api_usage.py           # Per-source daily quota tracking
│   │   ├── proxy_manager.py       # Proxy rotation (ip:port, ip:port:user:pass)
│   │   └── delays.py              # Random delay generators
│   ├── whatsapp_bot.py            # Playwright WhatsApp Web automation
│   └── whatsapp/
│       └── whatsapp_api.py        # 360dialog WhatsApp Business API client + webhook
├── src/db/
│   └── migrate.py                 # Idempotent schema migrations
├── tests/
│   ├── test_integration.py        # 9 integration tests
│   └── test_regressions.py        # 4 regression tests
├── scripts/
│   ├── precommit_check.py         # Compile + pyflakes sanity gate
│   └── agent_workspace.sh         # Git worktree manager for parallel agents
└── data/                          # SQLite DB + browser sessions (gitignored)
```

---

## Quick Start

### Prerequisites

- **Python 3.11+**
- **Playwright Chromium** — `playwright install chromium`
- **Groq API key** (free tier available) or Google Gemini key
- **Gmail account** with App Password (for email channel)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/TheSpideyBro/lead-gen-agent.git
cd lead-gen-agent

# 2. Create a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install Playwright browsers
playwright install chromium

# 5. Configure environment
copy .env.example .env       # Windows
# cp .env.example .env       # macOS / Linux
# Edit .env with your credentials

# 6. Run
python main.py
```

---

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and fill in your values:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GROQ_API_KEY` | Yes | — | Groq API key (primary LLM) |
| `GOOGLE_AI_API_KEY` | No | — | Google Gemini key (fallback LLM) |
| `EMAIL_ADDRESS` | Email channel | — | Gmail address for sending/receiving |
| `EMAIL_PASSWORD` | Email channel | — | Gmail **App Password** (not your login password) |
| `FROM_NAME` | No | — | Display name on outgoing emails |
| `SMTP_SERVER` | No | `smtp.gmail.com` | SMTP server host |
| `SMTP_PORT` | No | `587` | SMTP server port |
| `IMAP_SERVER` | No | `imap.gmail.com` | IMAP server host |
| `IMAP_PORT` | No | `993` | IMAP server port |
| `CALENDLY_LINK` | No | — | Booking link sent to interested leads |
| `TRACKING_BASE_URL` | No | `http://localhost:8080` | Email open tracking server URL |
| `TRACKING_SECRET` | **Yes** | — | HMAC secret for tracking pixel URLs (**must be set**) |
| `OWNER_PHONE` | No | — | Your phone for daily summaries & remote control |
| `OWNER_TIMEZONE` | No | `UTC` | IANA timezone (e.g. `America/New_York`) |
| `AI_MAX_RETRIES` | No | `3` | LLM retry attempts |
| `WHATSAPP_PROVIDER` | No | `web` | `web` (Playwright) or `api` (360dialog) |
| `D360_API_KEY` | WhatsApp API | — | 360dialog API key |
| `D360_PHONE_NUMBER_ID` | WhatsApp API | — | 360dialog sender number ID |
| `WHATSAPP_WEBHOOK_VERIFY_TOKEN` | Webhook | — | Meta challenge verification token |
| `WHATSAPP_WEBHOOK_SIGNING_SECRET` | Webhook | — | HMAC signature verification secret |
| `LINKEDIN_EMAIL` | LinkedIn scraper | — | LinkedIn login email |
| `LINKEDIN_PASSWORD` | LinkedIn scraper | — | LinkedIn login password |
| `LINKEDIN_DATA_DIR` | LinkedIn scraper | — | Session persistence path |
| `WHATSAPP_DATA_DIR` | WhatsApp | — | Session persistence path |
| `LEAD_DB_PATH` | No | `data/lead_bot.db` | SQLite database path |
| `APOLLO_API_KEY` | Apollo source | — | Apollo.io API key |
| `GITHUB_TOKEN` | GitHub source | — | GitHub personal access token |
| `PRODUCTHUNT_TOKEN` | ProductHunt source | — | ProductHunt developer token |
| `OUTREACH_LANGUAGE` | No | `auto` | `auto` / `english` / `native` |
| `GDPR_MODE` | No | `false` | Enable GDPR data-processing notices |
| `PROXY_LIST` | No | — | Comma-separated proxies for rotation |

> **Security note:** Never commit your `.env` file. It is excluded by `.gitignore`.

### Agency Profile

Edit `config/agency_profile.json` to define your agency name, services, ideal customer profile, case studies, and email signature. This drives all AI-generated outreach copy.

### Prospect Preferences

Adjust search keywords, daily limits, and working hours in `config/prospect_preferences.json`.

---

## Usage

Run `python main.py` and choose from the interactive menu:

| # | Option | Action |
|---|--------|--------|
| 1 | Prospect | Run DuckDuckGo / Google prospecting |
| 2 | Email Outreach | Send pending email sequences |
| 3 | WhatsApp Outreach | Send pending WhatsApp messages |
| 4 | Hot Leads | View leads with score ≥ 60 |
| 5 | Pending Follow-ups | View upcoming scheduled messages |
| 6 | Analytics | Generate matplotlib dashboard |
| 7 | Connect WhatsApp | One-time QR code scan |
| 8 | Email Replies | Check & classify email responses |
| 9 | WhatsApp Replies | Check & classify WhatsApp responses |
| 10 | LinkedIn | Run LinkedIn prospecting |
| 11 | Open Stats | View email open tracking data |
| 12 | Daily Summary | Send pipeline report to owner |
| 13 | Booking Pipeline | View qualified & booking leads |
| 14 | Exit | Graceful shutdown |

### Cron / Automation

Single-mode flags for scheduling via cron or Task Scheduler:

```bash
python main.py --prospect      # Discover new leads
python main.py --outreach       # Send due email follow-ups
python main.py --whatsapp       # Send due WhatsApp messages
python main.py --responses      # Process inbound replies
python main.py --report         # Refresh analytics chart
python main.py --summary        # Send daily summary
```

---

## Autonomous Mode

While `main.py` runs one action at a time, **`agent.py`** is a long-running supervisor that operates the entire pipeline unattended:

```bash
python agent.py            # Live 24/7 loop (prospects + sends for real)
python agent.py --test     # One dry-run pass (safe smoke test)
python agent.py --dry-run  # Full loop, logs only — no sends/writes
python agent.py --status   # Print state + health, then exit
python agent.py --pause    # Pause autonomous work
python agent.py --resume   # Resume autonomous work
```

> ⚠️ **Live by default.** Always test with `--test` or `--dry-run` first.

### What the Agent Does

| Task | Cadence | Action |
|------|---------|--------|
| `check_replies` | ~2 min | Poll email + WhatsApp, classify and handle replies |
| `send_initial_outreach` | ~5 min | Send due step-1 messages |
| `send_followups` | ~5 min | Send due follow-up steps |
| `prospect_new_leads` | ~1 h | Discover + score new leads (quota-aware) |
| `daily_report` | Once/day | Generate report + DM owner at 09:00 local |
| `weekly_cleanup` | Weekly | Prune logs + send leaderboard |

### Remote Control via WhatsApp

Message the bot from your `OWNER_PHONE` number:

| Command | Effect |
|---------|--------|
| `STATUS` | Current state, queues, per-task cadence |
| `PAUSE` / `RESUME` | Suspend / resume all autonomous work |
| `REPORT` | Generate and send pipeline report now |
| `STOP OUTREACH` | Disable prospecting + sending (replies continue) |
| `HOT LEADS` | Top hot leads |

---

## Development

### Project Structure

This project follows a modular layout under `src/`. Each subdirectory is a focused concern:

- **`src/database.py`** — Async SQLite layer with 10 tables and idempotent migrations
- **`src/ai_client.py`** — Multi-provider LLM client with instance-level rate limiting
- **`src/scrapers/`** — Five prospect sources, each self-disabling when API keys are missing
- **`src/outreach/`** — Email generation, sequencing, sending, and reply classification
- **`src/tracking/`** — HMAC-signed tracking pixels for email open detection
- **`src/compliance/`** — CAN-SPAM / GDPR footer builder and suppression list
- **`src/scheduling/`** — Timezone-aware, holiday-aware send slot calculator

### Running Tests

```bash
python -m pytest tests/ -v
```

**13 tests** covering schema+migration, ICP scoring, compliance, proxy parsing, and regressions. All stdlib-only (no extra dependencies required).

### Pre-commit Gate

```bash
python scripts/precommit_check.py
```

Runs `py_compile` and `pyflakes` on staged files to catch syntax errors and undefined names before commit.

### Adding a New Lead Source

1. Create `src/scrapers/<name>_scraper.py`
2. Implement `search_prospects()` returning `List[Lead]`
3. Register in `LeadScraper.find_global_prospects()`
4. Add API key to `.env.example` and `config/prospect_preferences.json`

---

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run a specific test class
python -m pytest tests/test_integration.py::TestCompliance -v

# Run with coverage
pip install pytest-cov
python -m pytest tests/ --cov=src --cov-report=term-missing
```

---

## Security

| Area | Protection |
|------|------------|
| **Tracking pixels** | HMAC-SHA256 signed URLs; secret required at startup |
| **WhatsApp webhook** | Meta challenge verification + HMAC signature over POST body |
| **Email signature** | `str.replace()` instead of `str.format()` — no `{` injection |
| **Input validation** | Email, phone, URL sanitization on all user-provided data |
| **Rate limiting** | Per-AI-client throttling; per-IP tracking server limits |
| **Secrets** | `.env` excluded from git; no hardcoded credentials in source |

---

## Compliance

| Regulation | Implementation |
|------------|---------------|
| **CAN-SPAM** | Physical address in footer, working opt-out link, sender identification |
| **GDPR** | Optional data-processing notice (`GDPR_MODE=true`), region-specific rules |
| **Opt-out detection** | Recognizes "STOP", "unsubscribe", "remove me", "opt out", etc. |
| **Suppression list** | Global `global_unsubscribe` table checked before every send |
| **Send logging** | Every outreach action logged for audit trail |

---

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| **v1.5** | ✅ Complete | Phone normalization, parallel enrichment, webhook dedup, holiday format robustness |
| **v1.4** | ✅ Complete | Critical fixes: atomic sends, tracking secret, webhook auth, orphan tasks, rate limiter |
| **v1.3** | ✅ Complete | Timezone-aware scheduling, holiday skipping, message localization |
| **v1.2** | ✅ Complete | Multi-source prospecting (Apollo, GitHub, ProductHunt), WhatsApp Business API |
| **v1.1** | ✅ Complete | CAN-SPAM/GDPR compliance, tracking pixels, reply classification |
| **v1.0** | ✅ Complete | Core pipeline: prospecting, scoring, email/WhatsApp outreach, daily reports |

### Planned

| Version | Target | Description |
|---------|--------|-------------|
| **v2.0** | Q3 2026 | Centralized config (`Settings` dataclass wired throughout), extracted `agent.py` modules |
| **v2.1** | Q3 2026 | Shared classification engine, enhanced DB indexes, CI/CD pipeline |
| **v3.0** | Q4 2026 | Web dashboard (FastAPI + React), CRM export (HubSpot/Pipedrive), multi-agency support |

---

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.

---

## Disclaimer

This tool automates outreach across email, WhatsApp, and LinkedIn. You are responsible for complying with the terms of service of each platform and with applicable anti-spam and data-protection laws (e.g. CAN-SPAM, GDPR). Use responsibly, respect opt-outs, and only contact prospects where you have a lawful basis to do so.
