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

## Recent fixes (v1.4.0)

A full code review was performed on 2026-06-13 and every finding was turned
into code on the [`agent/refactor-agent`](https://github.com/TheSpideyBro/lead-gen-agent/pull/new/agent/refactor-agent)
branch (now merged into `main` in v1.4.0). Here is the short list of what
broke and how it was fixed.

### 🐛 Critical bugs

| # | Problem | Fix |
|---|---------|-----|
| 1 | **Daily summary was always zero.** `daily_summary.py` queried a table called `message_sequences` that did not exist — every "emails sent today" / "pending follow-ups" stat returned 0. | Switched to the real `sequences` table. Added a regression test so it can never come back. |
| 2 | **First-run crash.** `data/` and its subdirectories were not auto-created, so a fresh clone threw `FileNotFoundError` on the very first SMTP send. | `get_db_path()` and `main.py` now `mkdir(parents=True, exist_ok=True)`. Added a `data/.gitkeep` sentinel. |
| 3 | **SMTP `sendmail()` was not concurrency-safe.** Two coroutines sharing a single `smtplib.SMTP` socket could interleave writes. | Per-instance `asyncio.Lock`; the connection is reset on transport errors. |
| 4 | **IMAP connection was leaked on exception.** `check_for_replies()` only closed the mailbox on the happy path. | Wrapped the IMAP session in `try/finally`. |
| 5 | **IMAP `FROM "user@host"` returned zero hits.** Gmail/Outlook interpret the quoted argument as a display name, not an address. | Switched to the RFC 3501 `(FROM "<user@host>")` address-atom, with a legacy fallback. |
| 6 | **WhatsApp `IndexError` on sidebar-opened chats.** The bot extracted the phone from the URL `phone=` query string, but sidebar clicks leave the URL empty. | New `_extract_phone_from_header()` reads the phone from the chat header DOM. |
| 7 | **Double-send race.** Two parallel cron invocations would pick the same `(lead, channel, step)` row and email the prospect twice. | New `UNIQUE(lead_id, channel, step)` index on `sequences`; `schedule_message()` is now insert-or-update. |
| 8 | **Booking outreach clobbered `qualified` leads.** A lead that had already qualified would be downgraded back to `booking_sent`. | New `_BOOKING_GUARD` set blocks the transition. |
| 9 | **Email signature `KeyError`.** A literal `{` in the operator's bio raised `KeyError` because the code used `str.format()`. | `_signature()` uses positional `str.replace()` and tolerates a missing/empty signature. |
| 10 | **Phone number misrouting.** `_format_phone("442071838750")` returned `"1442071838750"` — the "prepend 1 to any 10 digits" hack sent European prospects to a stranger in the NANP. | Uses `phonenumbers` (E.164-aware) with a safe digit-only fallback. |
| 11 | **"STOP" → "interested".** `_classify_incoming` returned `"question"` when the AI was unavailable, so the bot kept asking questions to opt-out messages. | Conservative fallback no longer auto-replies. Classification whitelist is unified. |
| 12 | **"Qualified" metric inflated.** Both the daily summary and the chart counted `hot + warm` instead of actual `qualified` leads. | Both now count `status = 'qualified'` only. |
| 13 | **SMTP socket leaks.** `EmailSender` was instantiated per booking outreach and per Calendly/answer email — 30 hot leads = 30 leaked sockets. | One `EmailSender` is now built in `build_components()` and shared across the whole process. |

### 🔐 Security

| # | Problem | Fix |
|---|---------|-----|
| 14 | **Tracking pixel was unauthenticated.** Anyone could hit `/track/1/1.png` to inflate a real lead's open count and bump its score by 15. | Every pixel URL is now signed with HMAC-SHA256 over `(lead_id, sequence_id, TRACKING_SECRET)`. Server validates with `hmac.compare_digest` and adds a per-IP sliding-window rate limit (10 req / 60 s). Set `TRACKING_SECRET` in `.env` before going to production. |
| 15 | **LLM HTML in email bodies / WhatsApp input.** The LLM sometimes returns HTML; we embedded it verbatim. | New `_html_escape()` helpers in both `EmailSender` and `WhatsAppBot`. |
| 16 | **Silent "STOP" → "interested".** MIME body bytes were decoded with `errors="ignore"`, so a mis-encoded opt-out could be silently misclassified and trigger the Calendly auto-reply. | Switched to `errors="replace"` + a `_decode` helper that logs a warning. |
| 17 | **PII in logs.** `logger.error(f"...{exc}")` echoed raw IMAP exceptions, which include the failing search command — i.e. recipient addresses. | Errors are now logged by exception class only. |

### 🏗️ Architecture

- New **`src/config.py`** — typed `Settings` dataclass with `ensure_data_dirs()` and required-key validation. Replaces 7+ scattered `os.getenv(...)` calls.
- New **`src/logging_setup.py`** — JSON-or-console formatter, rotating file handler, `LOG_JSON=1` opt-in. Replaces the inline `logging.basicConfig(...)` in `main.py`.
- New **`tests/test_regressions.py`** — 4 stdlib-only regression tests (B1, B2, B9, signature format-safety). All pass.
- New **`requirements-pinned.txt`** — fully-pinned dependency set including `phonenumbers==8.13.36` and `pyflakes==3.2.0` for reproducible builds.
- Removed the stale empty `src/ai/` directory and the unused `urllib.parse` alias import in `prospect_scraper.py`.
- `connect_whatsapp.py` now wraps the Playwright session in `try/finally` so QR-scan failures don't leak browser processes.

### How to verify

```bash
git checkout v1.4.0
cd worktrees/refactor-agent
python scripts/precommit_check.py \
    main.py connect_whatsapp.py \
    src/config.py src/database.py src/ai_client.py src/analytics.py \
    src/whatsapp_bot.py src/logging_setup.py \
    src/scrapers/prospect_scraper.py src/scrapers/linkedin_scraper.py \
    src/outreach/email_generator.py src/outreach/email_sender.py \
    src/outreach/email_response_handler.py src/outreach/response_handler.py \
    src/tracking/server.py src/tracking/tracker.py \
    src/reports/daily_summary.py \
    src/utils/validators.py src/utils/rate_limiter.py src/utils/__init__.py \
    tests/test_regressions.py
# expected: exit 0, no output

python -m unittest tests.test_regressions -v
# expected: Ran 4 tests in ~0.4s — OK
```

For the full Problem → Fix table and the migration notes, see [`CHANGELOG.md`](CHANGELOG.md).

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

## Development

This repo supports concurrent work by multiple agents, each in its own isolated
Git-worktree workspace (separate directory + branch, shared history) so they
never overwrite each other's files. A shared pre-commit gate
(`scripts/precommit_check.py`) blocks any commit that fails to compile or
references an undefined name.

```bash
scripts/agent_workspace.sh new <agent>     # spin up an isolated workspace
scripts/agent_workspace.sh list            # list workspaces
```

See **[WORKSPACES.md](WORKSPACES.md)** for the full workflow.

---

## Disclaimer

This tool automates outreach across email, WhatsApp, and LinkedIn. You are responsible for complying with the terms of service of each platform and with applicable anti-spam and data-protection laws (e.g. CAN-SPAM, GDPR). Use responsibly, respect opt-outs, and only contact prospects where you have a lawful basis to do so.

---

## License

Released under the MIT License.