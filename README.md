# Lead Generation Agent

> AI-powered sales automation for digital marketing agencies — automated prospecting, multi-channel outreach, and intelligent reply handling across **Email**, **WhatsApp**, and **LinkedIn**.

<p align="left">
  <img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/async-asyncio-green.svg" alt="Asyncio">
  <img src="https://img.shields.io/badge/AI-Groq%20%7C%20Gemini-orange.svg" alt="AI Providers">
  <img src="https://img.shields.io/badge/tests-13-passing-brightgreen.svg" alt="Tests">
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
| **Autonomous Agent** | `agent.py` runs the whole pipeline 24/7 unattended — self-scheduling tasks, reactive reply handling, health monitoring, and WhatsApp remote control. See [Autonomous Mode](#autonomous-mode-agentpy). |

---

## Recent fixes (v1.5.0, 2026-07-01) — Phase 2 Bug Fixes

| # | Problem | Fix |
|---|---------|-----|
| 2.1 | **Phone LIKE query routed replies to the wrong lead.** `_lead_id_by_phone()` matched on `LIKE '%last9digits%'`, so two leads sharing a suffix collided. | Added `normalize_phone()` (strips non-digits, handles `00` intl prefix) and `phone_normalized` column. Lookups now use exact equality on the normalized form. |
| 2.2 | **Footer skipped when body prose contained "unsubscribe".** `ensure_email_compliant()` checked a bare substring, so a legitimate email body mentioning "unsubscribe" prevented the compliant footer from being added. | Now checks for specific footer patterns (`"reply stop to unsubscribe"`, `"unsubscribe link"`, `"privacy policy"`, ESP markers like Mailchimp/SendGrid). |
| 2.3 | **Holiday JSON format dependency.** `_is_holiday()` assumed every entry was an ISO date string; silently missed holidays stored as dicts, integers, or alternative formats. | Parses ISO strings, `date`/`datetime` objects, `YYYYMMDD` integers, `DD/MM/YYYY` strings, and `{"date": ..., "name": ...}` dicts. |
| 2.4 | **Sequential email enrichment — 20 leads = 20 HTTP round trips.** `_enrich_leads()` and ProductHunt email fetching were purely sequential. | `asyncio.gather` with `Semaphore(5)` caps concurrency at 5 parallel requests. |
| 2.5 | **Webhook duplicate replies.** Meta may retry the same webhook delivery; no idempotency guard existed. | `whatsapp_responses.message_id TEXT UNIQUE` column + `is_seen_message_id()` check before processing. Duplicate `message.id` → skip. |

---

## Recent fixes (v1.4.2, 2026-07-01) — Phase 1 Critical Fixes

| # | Problem | Fix |
|---|---------|-----|
| 1.1 | **Tracking secret defaulted to `"change-me"`** — anyone could forge valid tracking pixel URLs. | `TRACKING_SECRET` is now required at startup; raises `RuntimeError` if unset. |
| 1.2 | **Non-atomic `log_outreach` + `mark_email_sent`** — a crash between the two steps left orphan rows. | New `log_outreach_and_mark_sent()` does INSERT + UPDATE in one transaction. |
| 1.3 | **Inter-process send race** — multiple cron processes could pick the same sequence row. | Atomic `claim_sequence_for_send()` (`UPDATE ... WHERE sent=0`); send only if `rowcount==1`. |
| 1.4 | **WhatsApp webhook had no authentication** — anyone could inject fake messages. | GET challenge verifies `hub.verify_token`; POST verifies `X-Hub-Signature-256` HMAC. |
| 1.5 | **Orphan `schedule_daily_summary` task** leaked on exit; month-end crash (`target.day + 1`). | Task tracked in `_background_tasks` set and cancelled on exit; `timedelta(days=1)` for safe date math. |
| 1.6 | **Global `_last_call_time` serialized all AI clients** through one lock. | Rate-limit state moved to instance attributes — each `AIClient` is independent. |

---

## Recent fixes (v1.4.1, 2026-06-14)

Post-merge cleanup of the v1.4.0 branch. No behavioral changes; everything is a
no-op at runtime.

- **17 unused imports / locals dropped** across 10 files (`main.py`,
  `src/analytics.py`, `src/config.py`, `src/database.py`,
  `src/outreach/email_response_handler.py`, `src/outreach/response_handler.py`,
  `src/reports/daily_summary.py`, `src/scrapers/prospect_scraper.py`,
  `src/utils/validators.py`, `tests/test_regressions.py`).
- **9 new integration tests** in [`tests/test_integration.py`](tests/test_integration.py):
  - `TestSchemaAndMigration` — real `LeadDatabase` + `migrate()` round-trip in a
    temp dir; verifies all 7 GLOBAL columns exist after `migrate()` and that
    `migrate()` is idempotent.
  - `TestICPScorerLogic` — signal delta is exactly +25 (not the cap-truncated
    value), score is capped at 100, tier thresholds are correct.
  - `TestCompliance` — footer is omitted when the body already contains
    `unsubscribe`; opt-out detection recognises the 6 common phrases.
  - `TestProxyParser` — both `ip:port` and `ip:port:user:pass` formats parse,
    round-robin and credential masking in `performance()` work.

| Check | Before | After |
|---|---|---|
| Test count | 4 | **13** (all pass) |
| `pyflakes` warnings | 19 | **0** |
| `py_compile` errors | 0 | **0** (across 35 files) |
| Module-import smoke test | 31/31 | **31/31** |

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
├── agent.py                      # Autonomous 24/7 supervisor (scheduler + decision engine + monitor + remote control)
├── connect_whatsapp.py           # One-time WhatsApp Web session setup
├── requirements.txt
├── config/
│   ├── agency_profile.json       # Your agency, services, ICP, case studies
│   └── prospect_preferences.json # Keywords, daily limits, working hours
├── src/
│   ├── database.py               # Async SQLite (aiosqlite) data layer
│   ├── ai_client.py              # Multi-provider LLM client (Groq / Gemini)
│   ├── analytics.py              # Stats + matplotlib reporting
│   ├── config.py                 # Typed Settings dataclass + env loading
│   ├── logging_setup.py          # JSON/console formatter, rotating file handler
│   ├── utils/
│   │   ├── validators.py         # Input validation, sanitization, phone normalization
│   │   ├── rate_limiter.py       # Rate limiting and retry utilities
│   │   └── api_usage.py          # Per-source daily quota tracking
│   ├── scrapers/
│   │   ├── prospect_scraper.py   # DuckDuckGo / Google search + email extraction
│   │   └── linkedin_scraper.py   # Playwright LinkedIn / Sales Navigator scraper
│   ├── outreach/
│   │   ├── email_sender.py       # SMTP sender + lead scorer
│   │   ├── email_generator.py    # AI message generation + sequence scheduler + booking outreach
│   │   └── email_response_handler.py  # IMAP polling + AI reply classification
│   ├── tracking/
│   │   ├── tracker.py            # Email open tracking pixel (HMAC-signed URLs)
│   │   └── server.py             # aiohttp tracking server
│   ├── reports/
│   │   └── daily_summary.py      # Daily stats aggregation
│   └── whatsapp_bot.py           # Playwright WhatsApp Web automation
├── src/whatsapp/
│   └── whatsapp_api.py           # 360dialog WhatsApp Business API client + webhook (HMAC auth)
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
| `OWNER_PHONE` | — | Phone number for daily summary delivery **and autonomous-agent remote control** |
| `OWNER_TIMEZONE` | — | IANA tz (e.g. `America/New_York`) — gates the agent's daily report + alert quiet-hours (default `UTC`) |
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

## Autonomous Mode (`agent.py`)

While `main.py` runs one action at a time, **`agent.py`** is a long-running
supervisor that operates the entire pipeline unattended. It *drives the same
service layer* as the CLI (it reuses `build_components`, `run_prospecting`,
`run_outreach`), so behaviour stays identical — it just decides *when* to run each
piece and reacts to inbound replies on its own. Every operation is wrapped so a
failure degrades one task rather than crashing the process.

```bash
python agent.py            # live 24/7 loop (prospects + sends for real)
python agent.py --test     # one dry-run pass of every task, then exit (safe smoke test)
python agent.py --dry-run  # full loop, but only logs intent — no sends/writes
python agent.py --status   # print last persisted state + health, then exit (read-only)
python agent.py --pause    # mark the agent paused in agent_state.json
python agent.py --resume   # mark the agent running again
```

> ⚠️ **Live by default.** `python agent.py` with no flags will prospect and send
> real outreach. Use `--test` / `--dry-run` first to confirm your configuration.

### What it does

- **Self-scheduling tasks** — six recurring jobs with *dynamic cooldowns* that
  tighten when there's work and back off when idle:

  | Task | Default cadence | Action |
  |------|-----------------|--------|
  | `check_replies` | ~2 min (60s–15m) | Poll email + WhatsApp, classify and handle replies |
  | `send_initial_outreach` | ~5 min (2m–30m) | Send due step-1 messages |
  | `send_followups` | ~5 min (2m–30m) | Send due follow-up steps |
  | `prospect_new_leads` | ~1 h (30m–6h) | Discover + score new leads (quota-aware) |
  | `daily_report` | once/day | Generate the report + DM the owner (at 09:00 owner-local) |
  | `weekly_cleanup` | weekly | Prune logs + DM a weekly leaderboard |

- **Reactive reply handling** — an 8-way classifier (interested, not&#8209;interested,
  question, out&#8209;of&#8209;office, unsubscribe, referral/wrong&#8209;person, auto&#8209;reply,
  neutral) routes each reply to the right action. Idempotent, so it never
  double-sends.
- **Self-monitoring** — appends every action to `data/agent_log.jsonl`, records
  health metrics every 5 minutes, and raises alerts (DM'd to the owner) on
  stalls, repeated task failures, API quota ≥ 80%, or a reply backlog / dropped
  WhatsApp session.
- **Crash recovery** — state is persisted to `data/agent_state.json` every tick;
  on restart it restores its pause state, task intervals, owner-message cursor,
  and "daily report already sent" flag. Stops gracefully on `Ctrl+C`.

### Remote control over WhatsApp

Once a WhatsApp session is connected and `OWNER_PHONE` is set, message the bot
**from the owner number** to steer it (sender is verified; others are ignored):

| Command | Effect |
|---------|--------|
| `STATUS` | Reply with current state, queues, and per-task cadence |
| `PAUSE` / `RESUME` | Suspend / resume all autonomous work (replies still handled) |
| `REPORT` | Generate and send the pipeline report now |
| `STOP OUTREACH` | Disable prospecting + sending (replies keep being handled) |
| `HOT LEADS` | Reply with the top hot leads |

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