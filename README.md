# Lead Generation Agent

> AI-powered sales automation for digital marketing agencies — automated prospecting, multi-channel outreach, and intelligent reply handling across **Email**, **WhatsApp**, and **LinkedIn**.

<p align="left">
  <img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/async-asyncio-green.svg" alt="Asyncio">
  <img src="https://img.shields.io/badge/AI-Groq%20%7C%20Gemini-orange.svg" alt="AI Providers">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey.svg" alt="License MIT">
</p>

---

## Overview

Lead Generation Agent is a standalone command-line tool that runs an end-to-end outbound sales pipeline. It discovers prospects, scores them, generates personalized multi-step outreach with an LLM, sends it over email and WhatsApp, and classifies inbound replies to auto-respond, qualify, or unsubscribe leads — all from a single CLI.

Built on `asyncio` for concurrent I/O, with a local SQLite store and pluggable AI providers (Groq primary, Google Gemini fallback).

---

## Features

| Capability | Description |
|------------|-------------|
| **Prospect Discovery** | DuckDuckGo HTML scraping (no API key) + optional Google Custom Search and LinkedIn/Sales Navigator scraping via Playwright |
| **Lead Scoring** | Weighted scoring on industry, company size, location, and contactability → Hot / Warm / Cold tiers |
| **AI Outreach Sequences** | 3-step nurture cadences for email and WhatsApp, with personalized copy generated per lead |
| **Hot Leads Booking** | Immediate Calendly link delivery for hot leads, bypassing nurture sequences |
| **Reply Intelligence** | IMAP + WhatsApp polling with AI classification (interested / question / not interested / out-of-office) and automated responses |
| **Auto-Qualification** | Interested leads receive a Calendly link and are promoted; opt-outs are unsubscribed and removed from sequences |
| **Daily Summary** | Automated daily WhatsApp report with pipeline stats (new leads, outreach, responses) |
| **Analytics** | Matplotlib dashboards summarizing pipeline health and outreach activity |
| **Input Validation** | Email and phone validation, string sanitization to prevent injection attacks |
| **Rate Limiting** | Built-in rate limiting for API calls and web scraping |

---

## Architecture

```
lead-gen-agent/
├── main.py                       # CLI entry point and menu loop
├── connect_whatsapp.py           # One-time WhatsApp Web session setup
├── requirements.txt
├── config/
│   ├── agency_profile.json       # Your agency, services, ICP, case studies
│   └── prospect_preferences.json # Keywords, daily limits, working hours
├── src/
│   ├── database.py               # Async SQLite (aiosqlite) data layer
│   ├── ai_client.py              # Multi-provider LLM client (Groq / Gemini)
│   ├── analytics.py              # Stats + matplotlib reporting
│   ├── utils/
│   │   ├── validators.py         # Input validation and sanitization
│   │   └── rate_limiter.py       # Rate limiting and retry utilities
│   ├── scrapers/
│   │   ├── prospect_scraper.py   # DuckDuckGo / Google search + email extraction
│   │   └── linkedin_scraper.py   # Playwright LinkedIn / Sales Navigator scraper
│   ├── outreach/
│   │   ├── email_sender.py       # SMTP sender + lead scorer
│   │   ├── email_generator.py    # AI message generation + sequence scheduler + booking outreach
│   │   └── email_response_handler.py  # IMAP polling + AI reply classification
│   ├── tracking/
│   │   ├── tracker.py            # Email open tracking pixel
│   │   └── server.py             # aiohttp tracking server
│   ├── reports/
│   │   └── daily_summary.py      # Daily stats aggregation
│   └── whatsapp_bot.py           # Playwright WhatsApp Web automation
└── data/                         # SQLite DB + browser sessions (gitignored)
```

---

## Quick Start

### Prerequisites

- Python **3.11+**
- A free [Groq API key](https://console.groq.com) (or Google Gemini key)
- A Gmail account with an [App Password](https://support.google.com/accounts/answer/185833) for sending/reading mail

### Installation

```bash
# 1. Clone
git clone https://github.com/TheSpideyBro/lead-gen-agent.git
cd lead-gen-agent

# 2. Create a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt
playwright install chromium

# 4. Configure environment
copy .env.example .env       # Windows  (cp on macOS/Linux)
# Edit .env with your credentials

# 5. Run
python main.py
```

---

## Configuration

### Environment Variables (`.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | ✅ | Primary AI provider key |
| `GOOGLE_AI_API_KEY` | — | Fallback AI provider (Gemini) |
| `EMAIL_ADDRESS` | ✅* | Gmail address for sending/receiving |
| `EMAIL_PASSWORD` | ✅* | Gmail **App Password** (not your login password) |
| `FROM_NAME` | — | Display name on outgoing email |
| `SMTP_SERVER` / `SMTP_PORT` | — | Defaults: `smtp.gmail.com` / `587` |
| `IMAP_SERVER` / `IMAP_PORT` | — | Defaults: `imap.gmail.com` / `993` |
| `CALENDLY_LINK` | — | Booking link sent to interested leads |
| `LINKEDIN_EMAIL` / `LINKEDIN_PASSWORD` | — | LinkedIn login for the scraper (optional) |
| `LINKEDIN_DATA_DIR` | — | LinkedIn session persistence path |
| `WHATSAPP_DATA_DIR` | — | WhatsApp session persistence path |
| `LEAD_DB_PATH` | — | SQLite database path (default: `data/lead_bot.db`) |
| `TRACKING_BASE_URL` | — | Email open tracking server URL |
| `OWNER_PHONE` | — | Phone number for daily summary delivery |
| `AI_MAX_RETRIES` | — | LLM retry attempts (default `3`) |
| `WHATSAPP_HEADLESS` | — | Set to `true` for headless browser mode |
| `LINKEDIN_HEADLESS` | — | Set to `true` for headless browser mode |

> \* Required only for the email channel.

### Agency Profile

Edit `config/agency_profile.json` to define your agency name, services, ideal customer profile, case studies, and email signature. This drives all AI-generated copy. Adjust search keywords and daily limits in `config/prospect_preferences.json`.

---

## Usage

Run `python main.py` and choose from the interactive menu:

| Option | Action |
|--------|--------|
| `1` | Run prospecting (DuckDuckGo / Google) |
| `2` | Send pending email outreach |
| `3` | Send pending WhatsApp outreach |
| `4` | View hot leads (score ≥ 60) |
| `5` | View pending follow-ups |
| `6` | Generate daily analytics report |
| `7` | Connect WhatsApp (one-time QR scan) |
| `8` | Check & classify email replies |
| `9` | Check & classify WhatsApp replies |
| `10` | Run LinkedIn prospecting |
| `11` | View email open stats |
| `12` | Send daily summary now |
| `13` | View booking pipeline |
| `14` | Exit |

### WhatsApp Setup

On first use, select **option 7**. A browser opens to WhatsApp Web — scan the QR code with your phone. The session persists in `data/whatsapp/`, so you only do this once.

---

## How It Works

**Outreach cadences** are scheduled the moment a lead is added and processed when due:

- **Email:** immediate → +48h → +96h
- **WhatsApp:** immediate → +24h → +72h

**Hot leads** (score ≥ 60) receive immediate Calendly booking outreach instead of waiting for sequences.

**Lead scoring** awards points for high-value industries, company size, target geography, and a discoverable email, then buckets leads into:

| Tier | Score | Priority |
|------|-------|----------|
| 🔥 Hot | 60+ | Strong fit — prioritize |
| 🌤️ Warm | 40–59 | Medium fit |
| ❄️ Cold | < 40 | Low priority |

**Reply handling** polls inbox and WhatsApp, classifies each message with the LLM, and acts automatically: interested → Calendly + qualify, question → AI answer, not-interested → unsubscribe and stop all sequences.

---

## Automation

Run with **no flags** for the interactive menu. Pass a **single mode flag** to run
that action once and exit — ideal for cron (Linux/macOS) or Task Scheduler (Windows).

| Flag | Action |
|------|--------|
| `--prospect` | Run DuckDuckGo/Google prospecting once |
| `--linkedin` | Run LinkedIn prospecting once |
| `--outreach` | Send pending email outreach once |
| `--whatsapp` | Send pending WhatsApp outreach once |
| `--responses` | Check & classify email replies once |
| `--report` | Generate the analytics report once |

```bash
python main.py --prospect     # discover new leads daily
python main.py --outreach      # send due email follow-ups
python main.py --responses     # process inbound replies
python main.py --report        # refresh the analytics chart
```

> Browser-based modes (`--linkedin`, `--whatsapp`) require a persisted Playwright
> session and won't complete headlessly without prior login. The flags are mutually
> exclusive — pass one per invocation.

---

## Disclaimer

This tool automates outreach across email, WhatsApp, and LinkedIn. You are responsible for complying with the terms of service of each platform and with applicable anti-spam and data-protection laws (e.g. CAN-SPAM, GDPR). Use responsibly, respect opt-outs, and only contact prospects where you have a lawful basis to do so.

---

## License

Released under the MIT License.