# Project Handoff — lead-gen-agent

> **Purpose:** Seamless context transfer for any AI agent or developer taking over this project.
> **Last updated:** 2026-07-01
> **Current version:** 1.5.0
> **Branch:** `main` (Phase 1 & 2 fixes committed)

---

## 1. What This Project Does

Lead Generation Agent is an **autonomous outbound sales automation system** for digital marketing agencies. It runs end-to-end: discovers prospects from multiple sources, scores them by fit, generates personalized multi-step outreach via email and WhatsApp using LLMs, sends the messages, and classifies inbound replies to auto-respond, qualify, or unsubscribe leads — all from a single CLI or 24/7 supervisor (`agent.py`).

**Core stack:** Python 3.11+, `asyncio`, SQLite (`aiosqlite`), Groq (primary LLM) / Google Gemini (fallback), SMTP (email), WhatsApp Web (Playwright) or WhatsApp Business API (360dialog), DuckDuckGo / Google Custom Search scrapers.

---

## 2. Repository Structure

```
lead-gen-agent/
├── main.py                       # CLI entry point and interactive menu loop
├── agent.py                      # Autonomous 24/7 supervisor (scheduler + decision engine + monitor)
├── connect_whatsapp.py           # One-time WhatsApp Web QR scan setup
├── pyproject.toml                # Project metadata, dependencies, build config
├── requirements.txt              # Dependency ranges
├── requirements-pinned.txt       # Fully pinned versions for reproducible builds
├── README.md                     # User-facing documentation
├── CHANGELOG.md                  # Detailed version history
├── WORKSPACES.md                 # Multi-agent git-worktree workflow
├── config/
│   ├── agency_profile.json       # Agency name, services, ICP, case studies, email signature
│   ├── prospect_preferences.json # Search keywords, daily limits, working hours
│   ├── compliance_rules.json     # Per-region sending rules (CAN-SPAM, GDPR)
│   └── global_holidays.json      # Country-code → holiday date lists (for timezone scheduler)
├── src/
│   ├── database.py               # LeadDatabase class — async SQLite with 10 tables
│   ├── ai_client.py              # AIClient — Groq / Gemini with instance-level rate limiting
│   ├── analytics.py              # Stats aggregation + matplotlib dashboard generation
│   ├── config.py                 # Settings dataclass (partially wired; 52 os.getenv calls remain)
│   ├── logging_setup.py          # JSON/console formatter, rotating file handler
│   ├── compliance/
│   │   └── compliance_handler.py  # Footer builder, opt-out detection, suppression list
│   ├── language/
│   │   └── lang_handler.py        # AI-assisted message localization by country
│   ├── outreach/
│   │   ├── email_sender.py        # SMTP sender with per-instance asyncio.Lock
│   │   ├── email_generator.py     # MessageGenerator + OutreachSequence (scheduling, booking)
│   │   └── email_response_handler.py  # IMAP polling + AI reply classification
│   ├── reports/
│   │   └── daily_summary.py       # Pipeline stats → WhatsApp message
│   ├── scheduling/
│   │   └── timezone_scheduler.py  # Holiday-aware, timezone-optimal send slot calculator
│   ├── scoring/
│   │   └── icp_scorer.py          # ICP scoring: title, funding, employees, signals
│   ├── scrapers/
│   │   ├── prospect_scraper.py    # DuckDuckGo / Google search + EmailExtractor
│   │   ├── apollo_scraper.py      # Apollo.io firmographic people search
│   │   ├── github_scraper.py      # GitHub technical founder search
│   │   ├── producthunt_scraper.py # ProductHunt active launcher search
│   │   └── linkedin_scraper.py    # Playwright LinkedIn / Sales Navigator scraper
│   ├── tracking/
│   │   ├── tracker.py             # HMAC-signed tracking pixel URL generator
│   │   └── server.py              # aiohttp tracking pixel receiver + open logger
│   ├── utils/
│   │   ├── validators.py          # Email/phone validation, sanitize, normalize_phone
│   │   ├── rate_limiter.py        # Retry + backoff utilities
│   │   ├── api_usage.py           # Per-source daily quota tracker
│   │   └── proxy_manager.py       # Proxy rotation (ip:port, ip:port:user:pass)
│   ├── whatsapp_bot.py            # Playwright WhatsApp Web automation bot
│   └── whatsapp/
│       └── whatsapp_api.py        # 360dialog WhatsApp Business API client + webhook
├── src/db/
│   └── migrate.py                 # Idempotent schema migrations (ALTER TABLE guards)
├── tests/
│   ├── test_integration.py        # 9 integration tests (schema, ICP, compliance, proxy)
│   └── test_regressions.py        # 4 regression tests (table name, signature, phone, data dir)
└── data/                          # SQLite DB, browser sessions, agent state (gitignored)
```

---

## 3. Completed Tasks

### Phase 1 — Critical Fixes (2026-07-01)
Branch: `fix/phase-1-critical`

| # | Fix | Files Changed |
|---|-----|---------------|
| 1.1 | `TRACKING_SECRET` now required at startup (was `"change-me"`) | `tracker.py`, `config.py` |
| 1.2 | Atomic `log_outreach_and_mark_sent()` — one transaction | `database.py`, `email_generator.py` |
| 1.3 | Atomic `claim_sequence_for_send()` — prevents duplicate sends | `database.py`, `email_generator.py` |
| 1.4 | WhatsApp webhook auth — Meta challenge + HMAC signature | `whatsapp_api.py` |
| 1.5 | Background task tracking + cancellation on exit | `main.py` |
| 1.5 | Month-end crash fix (`timedelta(days=1)`) | `main.py` |
| 1.6 | Instance-level AI rate limiter (was global) | `ai_client.py` |

### Phase 2 — Bug Fixes (2026-07-01)

| # | Fix | Files Changed |
|---|-----|---------------|
| 2.1 | Phone LIKE query → normalized exact match via `phone_normalized` column | `validators.py`, `database.py`, `whatsapp_api.py` |
| 2.2 | Compliance footer — precise pattern matching instead of bare `"unsubscribe"` substring | `compliance_handler.py` |
| 2.3 | Holiday JSON — robust parsing (ISO, date objects, YYYYMMDD, DD/MM/YYYY, dicts) | `timezone_scheduler.py` |
| 2.4 | Email enrichment parallelized with `asyncio.gather` + `Semaphore(5)` | `prospect_scraper.py` |
| 2.5 | Webhook deduplication via `message_id TEXT UNIQUE` + `is_seen_message_id()` check | `database.py`, `whatsapp_api.py`, `migrate.py` |

### Test Status
- **13 tests** — all passing (stdlib-only, no extra deps)
- `test_integration.py`: 9 tests (schema+migration, ICP scoring, compliance, proxy parser)
- `test_regressions.py`: 4 tests (daily summary table name, signature safety, phone normalization, data dir autocreate)

---

## 4. Current Status

### What works today
- End-to-end CLI pipeline (`main.py`) — prospecting, outreach, reply handling, analytics
- Autonomous 24/7 supervisor (`agent.py`) — self-scheduling, reply handling, health monitoring, crash recovery, WhatsApp remote control
- Multi-channel outreach: email (SMTP) + WhatsApp (Playwright bot or 360dialog API)
- AI-generated personalized copy via Groq or Google Gemini
- Timezone-aware scheduling with holiday skipping
- Language localization of messages by recipient country
- CAN-SPAM / GDPR compliance: opt-out detection, suppression list, footer builder
- HMAC-signed tracking pixels for email open tracking
- Proxy rotation for scraping resilience
- Phone number normalization and deduplication

### Known limitations (not yet addressed)
- **`config.py` `Settings` dataclass exists but is not wired** — 52 `os.getenv()` calls scattered across files. Phase 4 will consolidate.
- **`agent.py` is a 1700+ line god object** — Phase 4 will extract `TaskScheduler`, `DecisionEngine`, `AgentMonitor`.
- **Classification logic duplicated in 4 places** — Phase 4 will extract a shared classifier.
- **Missing DB indexes** on `sequences(channel, sent, scheduled_for)`, `email_responses(replied)`, `whatsapp_responses(received_at)`.
- **No `pyproject.toml` existed before today** — now created with full metadata.

---

## 5. Future Roadmap

### Phase 3 — Security Hardening (next)
| # | Issue | Approach |
|---|-------|----------|
| 3.1 | Owner phone `endswith(-10:)` allows unauthorized remote control | Full normalized-E.164 equality check against `OWNER_PHONE` |
| 3.2 | PII in logs (emails, phones written unmasked) | Logging filter that redacts emails/phones |
| 3.3 | Prompt injection via unsanitized user messages in AI calls | Delimit user text as data, strip control chars, cap length, validate output |
| 3.4 | Tracking server binds `0.0.0.0` without TLS | Default to `127.0.0.1`; explicit opt-in for `0.0.0.0`; signed-pixel TTL |

### Phase 4 — Architecture Improvements
| # | Issue | Approach |
|---|-------|----------|
| 4.1 | Wire up `config.py` `Settings` — replace scattered `os.getenv()` | `load_settings()` at entry point; inject into components |
| 4.2 | Extract `agent.py` god object (>1700 lines) | Split into `src/agent/{scheduler.py, decision_engine.py, monitor.py, agent.py}` |
| 4.3 | Add missing DB indexes | `idx_seq_pending`, `idx_resp_replied`, `idx_wa_resp_received`, `idx_leads_phone_norm` |
| 4.4 | Centralize classification logic | New `src/classification/classifier.py`; replace 4 copies |

### Phase 5 — Test Coverage
| # | Target | Tests to add |
|---|--------|-------------|
| 5.1 | DecisionEngine | All 8 `_normalize` mappings, opt-out wins, idempotent re-run, OOO vs auto-reply |
| 5.2 | Outreach atomicity | Concurrent claim → one send; suppressed skip; footer once |
| 5.3 | Webhook auth | Bad signature → 401; duplicate message.id → one effect; exact phone match |
| 5.4 | Classifier | Whitelist enforcement; injection → safe label |
| 5.5 | Config | Required raises; `_int`/`_bool` coercion; `tracking_port` |
| 5.6 | CI | GitHub Actions workflow with `pytest` on push |

### Nice-to-have enhancements
- **LinkedIn scraping reliability** — currently fragile with Playwright; consider SerpAPI or Apollo as primary source
- **WhatsApp Business API template pre-approval flow** — automate template submission to Meta
- **Multi-agency support** — config-driven profiles for managing multiple agencies
- **Web dashboard** — FastAPI + React frontend for real-time pipeline visibility
- **CRM export** — CSV/HubSpot/Pipedrive integration

---

## 6. Running the Project

### Prerequisites
- Python 3.11+
- Playwright Chromium: `playwright install chromium`
- API keys in `.env` (copy `.env.example`)

### Quick start
```bash
pip install -r requirements.txt
python main.py              # Interactive menu
python agent.py --test      # Dry-run all tasks (safe)
python agent.py             # 24/7 autonomous mode
```

### Testing
```bash
python -m pytest tests/ -v   # 13 tests, all pass
```

### Migration
```bash
python -m src.db.migrate     # Idempotent; safe to run anytime
```

---

## 7. Key Design Decisions

1. **SQLite over PostgreSQL** — single-user, local-first, zero infrastructure. Adequate for solo operator.
2. **aiosqlite throughout** — no sync/async mixing; the entire pipeline is async.
3. **Instance-level rate limiting** — each `AIClient` manages its own throttle; no global serialization.
4. **Atomic sequence claiming** — `UPDATE ... WHERE sent=0` prevents duplicate sends under concurrent cron.
5. **Normalized phone matching** — `phone_normalized` column enables exact equality lookups instead of fuzzy LIKE.
6. **HMAC-signed tracking pixels** — prevents URL forgery; server validates signature + per-IP rate limit.
7. **Webhook auth** — Meta challenge verification + HMAC signature over POST body.
8. **Idempotent migrations** — `ALTER TABLE` guarded by `PRAGMA table_info`; safe to run repeatedly.
9. **Graceful degradation** — every AI call, scraper, and sender has try/except with safe defaults.

---

## 8. Environment Variables Reference

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `GROQ_API_KEY` | Primary | — | Main LLM provider |
| `GOOGLE_AI_API_KEY` | Fallback | — | Gemini fallback |
| `TRACKING_SECRET` | **Yes** | — | HMAC signing for tracking pixels |
| `EMAIL_ADDRESS` | For email | — | Gmail address |
| `EMAIL_PASSWORD` | For email | — | Gmail App Password |
| `OWNER_PHONE` | For agent | — | WhatsApp remote control + daily summary |
| `OWNER_TIMEZONE` | — | `UTC` | IANA timezone for scheduling |
| `WHATSAPP_WEBHOOK_VERIFY_TOKEN` | For webhook | — | Meta challenge token |
| `WHATSAPP_WEBHOOK_SIGNING_SECRET` | For webhook | — | HMAC signature verification |
| `D360_API_KEY` | For WhatsApp API | — | 360dialog API key |
| `D360_PHONE_NUMBER_ID` | For WhatsApp API | — | Sender phone number ID |
| `LEAD_DB_PATH` | — | `data/lead_bot.db` | SQLite database location |
| `GDPR_MODE` | — | `false` | Adds data-processing notice |
| `PROXY_LIST` | — | — | Comma-separated proxies for rotation |
| `OUTREACH_LANGUAGE` | — | `auto` | `auto` / `english` / `native` |
| `WHATSAPP_PROVIDER` | — | `web` | `web` (Playwright) or `api` (360dialog) |

---

## 9. Git Workflow

This repo uses **git worktrees** for parallel multi-agent collaboration:

```bash
scripts/agent_workspace.sh new <agent-name>   # Creates isolated worktree
scripts/agent_workspace.sh list                # Lists active worktrees
```

Each worktree gets its own branch and directory, sharing the same history. A pre-commit gate (`scripts/precommit_check.py`) blocks commits that fail `py_compile` or reference undefined names.

**Branch convention:**
- `main` — stable, tested code
- `fix/phase-N-description` — fix branches (e.g., `fix/phase-1-critical`)
- Pre-commit: run `python -m pytest tests/ -v` and `python scripts/precommit_check.py` on touched files

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `FileNotFoundError` on first run | `data/` directory missing | Auto-created by `get_db_path()` |
| Tracking pixel returns 403 | `TRACKING_SECRET` not set | Copy `.env.example` to `.env` and set the secret |
| WhatsApp messages fail | QR session expired | Run `python connect_whatsapp.py` to re-scan |
| Email sends duplicate | Race between cron invocations | Fixed in v1.4.2 — atomic claim prevents this |
| Wrong lead gets WhatsApp reply | Phone LIKE suffix collision | Fixed in v1.5.0 — normalized exact match |
| Holiday skipping broken | Non-standard JSON date format | Fixed in v1.5.0 — tolerates multiple formats |

---

*End of handoff. For questions, see `README.md` or `CHANGELOG.md`.*
