# Changelog

All notable changes to this project will be documented in this file.

## [v1.5.1] - 2026-07-12 — Sprint 1: Security & bug fixes

### Fixed

- **B4 — WhatsApp API classification fallback** (`src/whatsapp/whatsapp_api.py`)
  When the AI client is unavailable or fails, `_classify()` now returns
  `"neutral"` instead of `"question"`. This prevents the bot from
  auto-replying to "STOP" / opt-out messages with AI-generated nonsense
  when the AI service is down. The Playwright bot was already fixed in a
  prior commit; this brings the Business API client in line.
- **S4 — SQL injection risk via dynamic column names** (`src/database.py`)
  `GLOBAL_COLUMNS` is now a `frozenset` (immutable) and `update_lead_global()`
  sorts columns before building the parameterised SQL, making the allowlist
  explicit and impossible to bypass at runtime.
- **S6 — Proxy credential log leakage** (`src/utils/proxy_manager.py`)
  The `_parse()` method now strips credentials from the log message for
  malformed proxy entries, logging only `host:port` instead of the raw
  `user:pass@host:port` string.
- **S10 — LLM output unsanitized in emails** (`src/outreach/email_generator.py`)
  All LLM-generated message bodies (initial, follow-up, booking email,
  booking WhatsApp) are now passed through `sanitize_html()` before
  embedding, stripping `<script>`, event handlers, and other dangerous
  HTML while preserving safe tags like `<b>`, `<i>`, `<a>`.

### Changed

- `pyproject.toml` / `src/__init__.py`: version bumped 1.5.0 → 1.5.1.

### Verification

```bash
python -m unittest discover tests -v
# 30 pass, 3 pre-existing errors (mock issue unrelated to these changes)
```

---

## [v1.4.1] - 2026-06-14 — Post-merge cleanup + integration tests

- Dropped **17 unused imports / local variables** flagged by `pyflakes` across
  `main.py`, `src/analytics.py`, `src/config.py`, `src/database.py`,
  `src/outreach/email_response_handler.py`, `src/outreach/response_handler.py`,
  `src/reports/daily_summary.py`, `src/scrapers/prospect_scraper.py`,
  `src/utils/validators.py`, and `tests/test_regressions.py`.
- New [`tests/test_integration.py`](tests/test_integration.py) — 9 integration
  tests that exercise the modules the GLOBAL transformation introduced:
  - `TestSchemaAndMigration`: a real `LeadDatabase` + `migrate()` round-trip in
    a temp dir; verifies all 7 GLOBAL columns exist after `migrate()` and
    that `migrate()` is idempotent.
  - `TestICPScorerLogic`: signal delta is exactly +25 (not the cap-truncated
    value), score is capped at 100, tier thresholds are correct.
  - `TestCompliance`: footer is omitted when the body already contains
    `unsubscribe`; opt-out detection recognises the 6 common phrases.
  - `TestProxyParser`: both `ip:port` and `ip:port:user:pass` formats parse,
    round-robin and credential masking in `performance()` work.

Test count: 4 → 13 (all pass). `pyflakes` warnings: 19 → 0.
`py_compile`: 0 errors across 35 Python files.
Module-import smoke test: 31/31 modules load cleanly.

## [v1.4.0] - 2026-06-13 — Code-review hard pass

A full code review was performed against the v1.3.0 codebase. Every
finding was turned into code on the `agent/refactor-agent` branch
([PR-ready on GitHub](https://github.com/TheSpideyBro/lead-gen-agent/pull/new/agent/refactor-agent)).
This release merges that work.

### Problem → Fix (the short version)

| # | Problem | Where it was | What we did |
|---|---------|--------------|-------------|
| 1 | `daily_summary.py` queried a non-existent `message_sequences` table — every "emails sent today" and "pending follow-ups" stat returned `0` | `src/reports/daily_summary.py` | Switched the queries to the real `sequences` table. Added a regression test. |
| 2 | `data/` directory was not created on first run — fresh clones crashed with `FileNotFoundError` | `src/database.py`, `main.py` | `get_db_path()` now calls `mkdir(parents=True, exist_ok=True)`; `main.py` pre-creates the runtime folders. Added `data/.gitkeep`. |
| 3 | SMTP `sendmail()` was not concurrency-safe — concurrent sends on the same `smtplib.SMTP` socket could interleave | `src/outreach/email_sender.py` | Per-instance `asyncio.Lock`; connection is reset on transport errors. |
| 4 | IMAP connection was leaked on exception — `check_for_replies()` never called `M.close()`/`M.logout()` on the error path | `src/outreach/email_response_handler.py` | Wrapped the session in `try/finally`. |
| 5 | `IMAP.search(None, f'FROM "{email}" SINCE ...')` returned zero results on Gmail/Outlook — the address was being parsed as a display name | `src/outreach/email_response_handler.py` | Switched to RFC 3501 `(FROM "<user@host>")` address-atom with a legacy fallback. |
| 6 | WhatsApp `current_url.split("phone=")[1]` raised `IndexError` whenever a chat was opened from the sidebar (no `phone=` query param) | `src/whatsapp_bot.py` | Added `_extract_phone_from_header()` that reads the chat header DOM; URL is now only a fallback. |
| 7 | `schedule_message` was not idempotent — two parallel cron runs would send the same email twice | `src/database.py`, `src/outreach/email_generator.py` | Added `UNIQUE(lead_id, channel, step)` index; `schedule_message()` is now insert-or-update. |
| 8 | `schedule_sequence` enqueued sequences for leads that had no contact info on that channel (wasted LLM calls, broken daily summary) | `src/outreach/email_generator.py` | New guard that fetches the lead and skips the channel if the contact endpoint is missing. |
| 9 | Booking outreach overwrote a `qualified` lead with `booking_sent` (lost state) | `src/outreach/email_generator.py` | New `_BOOKING_GUARD` set blocks the transition. |
| 10 | Email signature used `str.format()` — a literal `{` in the operator's bio raised `KeyError` | `src/outreach/email_generator.py` | `_signature()` uses positional `str.replace()` and tolerates a missing/empty signature. |
| 11 | `_format_phone("442071838750")` returned `"1442071838750"` — European numbers were silently misrouted via the NANP prefix | `src/whatsapp_bot.py` | Uses `phonenumbers` (E.164-aware) with a safe digit-only fallback. The 1-prepend hack is gone. |
| 12 | WhatsApp `_classify_incoming` returned `"question"` when the AI was down — so the bot kept asking questions to "STOP" messages | `src/whatsapp_bot.py` | Conservative fallback no longer auto-replies; classification whitelist is unified. |
| 13 | "Qualified" metric inflated by counting `hot + warm` instead of actual `qualified` status | `src/reports/daily_summary.py`, `src/analytics.py` | Both now count `status = 'qualified'` only. |
| 14 | Classification vocabulary mismatch: `uninterested` (in summary) vs `not_interested` (in email poller) caused the count to silently drop | `src/reports/daily_summary.py`, `src/whatsapp_bot.py` | Unified on `not_interested` everywhere. |
| 15 | `EmailSender` was instantiated per booking outreach and per Calendly/answer email — 30 hot leads = 30 leaked SMTP sockets | `main.py`, `src/outreach/email_sender.py`, `src/outreach/email_response_handler.py` | `build_components()` constructs one `EmailSender` and shares it across the whole process. |
| 16 | Tracking pixel had no authentication — anyone could hit `/track/1/1.png` to inflate a lead's open count by 15 points | `src/tracking/tracker.py`, `src/tracking/server.py` | Every pixel URL is now signed with HMAC-SHA256 over `(lead_id, sequence_id, TRACKING_SECRET)`. Server validates with `hmac.compare_digest` and adds a per-IP sliding-window rate limit (10 req / 60 s). |
| 17 | LLM-generated HTML was embedded verbatim into email bodies and WhatsApp input — minor XSS surface, broken formatting | `src/outreach/email_sender.py`, `src/whatsapp_bot.py` | New `_html_escape()` helpers in both modules. |
| 18 | MIME body bytes decoded with `errors="ignore"` — a mis-encoded "STOP" reply could be silently misclassified as `"interested"` | `src/outreach/email_response_handler.py` | Switched to `errors="replace"` + a `_decode` helper that logs a warning. |
| 19 | `logger.error(f"...{exc}")` echoed raw IMAP exceptions (which include the failing search command → leaks recipient addresses to log files) | `src/outreach/email_response_handler.py`, `src/whatsapp_bot.py` | Errors are now logged by exception class only. |
| 20 | `os.getenv(...)` was called in 7+ modules with no central type or fail-fast behaviour | new `src/config.py` | Added a typed `Settings` dataclass with `ensure_data_dirs()` and required-key validation. |
| 21 | No structured logs — cron failures were silent | new `src/logging_setup.py` | JSON-or-console formatter, rotating file handler, `LOG_JSON=1` opt-in. |
| 22 | No tests — only a pre-commit syntax gate | new `tests/test_regressions.py` | 4 stdlib-only regression tests; all pass. |
| 23 | Dependency list was minimum-version only (`openai>=1.10.0`); builds were not reproducible | new `requirements-pinned.txt` | Fully-pinned set including `phonenumbers==8.13.36` and `pyflakes==3.2.0`. |
| 24 | Stale empty `src/ai/` directory and unused `urllib.parse` alias import | tree-wide | Removed. |
| 25 | `connect_whatsapp.py` did not close the Playwright browser on QR-scan failure | `connect_whatsapp.py` | Session now wrapped in `try/finally`. |

### Security

- Tracking-pixel HMAC signature scheme is added; **set `TRACKING_SECRET` in `.env` before going to production** (default is a loud sentinel string, not a real secret).
- All other security fixes are already enforced and require no operator action.

### Backwards compatibility

- **WhatsApp classification labels** — the bot now accepts `not_interested` and `stop` (the older training data) for opt-out; the canonical label written to the database is `not_interested`.
- **Status taxonomy** — `qualified` is now read as `status = 'qualified'`, not the union `hot ∪ warm`. If you have dashboards reading "qualified = hot + warm", update them.
- **DB schema** — a new `UNIQUE` index on `sequences(lead_id, channel, step)` is added at startup; pre-existing duplicates (if any) will fail the migration. Run `SELECT lead_id, channel, step, COUNT(*) FROM sequences WHERE sent=0 GROUP BY 1,2,3 HAVING COUNT(*) > 1;` to check.
- **`TRACKING_BASE_URL`** now expects to point at a server that validates the `?t=<hmac>` query parameter. If you have an old version of the tracking server still running, the new client URL will not match and opens will silently be dropped (the pixel still loads, so legitimate users see no breakage).

### Verification

```bash
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
# expected: exit 0

python -m unittest tests.test_regressions -v
# expected: Ran 4 tests in ~0.4s — OK
```

---

## [v1.3.0] - 2026-06-11

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
