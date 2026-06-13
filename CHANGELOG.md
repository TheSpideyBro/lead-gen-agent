# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased] - 2026-06-13

### Fixed (P0 — Critical bugs)
- **`daily_summary.py` queried the wrong table** (`message_sequences` did not
  exist) — every "emails sent today / pending follow-ups" stat returned 0.
  Now queries the real `sequences` table.
- **`data/` directory was not auto-created on first run** —
  `LeadDatabase.get_db_path()` now creates the parent directory and `main.py`
  pre-creates the runtime folders. A `data/.gitkeep` was added.
- **SMTP sendmail() was not concurrency-safe** — `EmailSender` now serializes
  sends with an `asyncio.Lock` and resets the connection on transport errors.
- **IMAP connection was leaked on exception** — `check_for_replies()` now
  uses `try/finally` to always `close()` and `logout()`.
- **IMAP `FROM "user@host"` query returned zero results on Gmail/Outlook** —
  switched to the RFC 3501 `(FROM "<user@host>")` address-atom form, with a
  graceful fallback to the legacy syntax.
- **WhatsApp URL parsing raised `IndexError` on sidebar-opened chats** —
  reads the phone from the chat header DOM and falls back to the URL.

### Fixed (P1 — Logic / safety)
- **`schedule_sequence` no longer enqueues for leads with no contact info**
  on the requested channel (no LLM cost, no confusing summary stats).
- **`schedule_message` is now idempotent** — a `UNIQUE(lead_id, channel, step)`
  index prevents duplicate sends when two cron invocations overlap.
- **Booking outreach no longer clobbers a `qualified` / `booking_sent` /
  `unsubscribed` lead** — explicit guard set in `OutreachSequence`.
- **Email signature `.format()` no longer raises `KeyError`** when the
  signature contains a literal `{` — replaced with positional
  `str.replace()`.
- **`WhatsAppBot._format_phone()` no longer misroutes non-NANP numbers** —
  uses `phonenumbers` if available, otherwise falls back to plain digit
  validation. Removed the silent "prepend 1 to any 10 digits" hack.
- **WhatsApp classifier no longer falls back to `question` on "STOP"** —
  the conservative default avoids auto-replying to opt-outs when the AI
  provider is down.
- **Unified classification vocabulary** — `not_interested` everywhere
  (was `uninterested` in `daily_summary.py`).
- **Status taxonomy corrected** — "qualified" now means a lead actually
  qualified (status = `qualified`), not merely high-scoring.

### Changed (P2 — Architecture)
- Added **centralised `Settings` dataclass** in `src/config.py` so the
  scattered `os.getenv(...)` calls can be replaced incrementally and
  missing required keys fail fast at startup.
- Added **structured JSON logging** in `src/logging_setup.py`, with a
  rotating file handler and a `LOG_JSON` env var to switch output mode.
- **Removed the empty `src/ai/` directory** and unused `urllib.parse`
  alias import in `prospect_scraper.py`.
- Added a `requirements-pinned.txt` for reproducible builds.
- Added a `tests/test_regressions.py` smoke suite (stdlib-only) that
  guards against the bugs above.
- `EmailSender` is now a singleton in `build_components()` and shared
  by `OutreachSequence`, `EmailResponsePoller`, and the booking flow
  — fixes 30-connection SMTP leaks for 30 hot leads.
- `WhatsAppBot.send_message` now HTML-escapes the body so an LLM
  returning HTML doesn't break the recipient's client.

### Security (P3)
- **Tracking pixel now requires an HMAC signature** in the URL
  (`?t=<hex>`) — the server validates it with `hmac.compare_digest` and
  silently drops unsigned hits. Adds a per-IP sliding-window rate limit
  (10 req / 60 s) for defense in depth.
- **IMAP error logs no longer echo raw exceptions** that include the
  failing search command (which leaks recipient addresses).
- **MIME body bytes are decoded with `errors="replace"`** instead of
  `errors="ignore"`, so a mis-encoded reply cannot be silently
  mis-classified as `interested`.
- Added `TRACKING_SECRET` env var; default `"change-me"` is a loud
  sentinel, not a real secret.

## [v1.3.0] - 2026-06-11

### Added
- **Daily Summary Feature** (`src/reports/daily_summary.py`)
  - Aggregates daily statistics (new leads, emails sent, WhatsApp sent, responses, hot/qualified leads, pending follow-ups)
  - Formats and delivers WhatsApp report to owner's phone
  - Automatic daily delivery at 9:00 AM via background task
  - Manual trigger via menu option 12

- **Hot Leads Booking Outreach**
  - Immediate Calendly link delivery for hot leads (score ≥ 60)
  - `OutreachSequence.send_booking_outreach()` method with AI-generated messages
  - Email subject: "Quick 15-min call — {company_name}?"
  - WhatsApp messages kept under 100 words
  - Logs outreach with `channel="booking"` to database
  - Updates lead status to `"booking_sent"`

- **Booking Pipeline View**
  - Menu option 13 displays leads with `booking_sent` or `qualified` status
  - Phone and email details shown for quick access

### Changed
- Updated `run_prospecting()` to trigger booking outreach for hot leads instead of standard sequences
- Added `OWNER_PHONE` and `LINKEDIN_PASSWORD` to `.env.example`
- Enhanced architecture diagram in documentation

### Fixed
- All modules compile successfully with Python 3.11+

---

## [v1.2.0] - 2026-06-10

### Added
- **Email Open Tracking** (`src/tracking/`)
  - Tracking pixel injection in outbound emails
  - Background aiohttp server for pixel endpoint
  - Automatic lead re-scoring on email open (+15 points)
  - Per-step open rate statistics (menu option 11)

- **LinkedIn Scraper** (`src/scrapers/linkedin_scraper.py`)
  - Playwright-based LinkedIn Sales Navigator scraping
  - Cookie persistence in `data/linkedin/`
  - Extract: name, title, company, website, location
  - 3-8 second randomized delays between profile visits

### Fixed
- SQL Tuple syntax error in `get_leads_by_status()`
- Missing datetime import in `database.py`
- Missing EmailSender import in `email_response_handler.py`
- Wrong commit call in `whatsapp_bot.py`
- Email-table mismatch (email_sequences → message_sequences)
- f-string syntax error in `linkedin_scraper.py`
- NULL field handling in `LeadScorer.score_lead()`
- Column index bugs in "View hot leads" and pending WhatsApp displays
