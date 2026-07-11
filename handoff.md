# Handoff Document — Lead Generation Agent

> **Purpose:** This file captures the full project context so another AI agent (or a human developer) can understand the codebase, pick up where work left off, and continue development without reading every source file from scratch.
>
> **Last updated:** 2026-07-02
> **Branch with all completed work:** `fix/phase-1-critical`
> **Production entry point:** `main.py` (interactive menu) or `python main.py --<mode>` (cron/CLI)
> **Autonomous agent entry point:** `agent.py` (standalone AI brain, ~1770 lines)

---

## 1. Project Purpose

**Lead Generation Agent** is an AI-powered outbound sales automation system. It discovers prospects from multiple sources (Google, DuckDuckGo, Apollo, GitHub, ProductHunt, LinkedIn), scores them against an Ideal Customer Profile (ICP), and conducts multi-channel outreach via email and WhatsApp — all driven by AI-generated personalized messages. It includes compliance handling (CAN-SPAM/GDPR), timezone-aware scheduling, email open tracking via HMAC-signed pixels, response classification, and automated reply generation.

---

## 2. Architecture Overview

```
main.py                  ← Interactive menu / cron entry point
agent.py                 ← Standalone autonomous AI agent (decision engine)

src/
├── config.py            ← Centralised Settings dataclass (fails-fast on missing keys)
├── database.py          ← aiosqlite wrapper: leads, sequences, responses, email_opens, global_unsubscribe
├── ai_client.py         ← Groq / Google Gemini abstraction with rate limiting & retries
├── logging_setup.py     ← JSON or console formatter, rotating file handler
│
├── outreach/
│   ├── email_generator.py   ← MessageGenerator (AI prompts) + OutreachSequence (scheduling, compliance, localization)
│   ├── email_sender.py      ← EmailSender (SMTP with asyncio.Lock) + LeadScorer
│   ├── email_response_handler.py  ← IMAP poller for inbound replies
│   └── response_handler.py  ← Legacy classification dispatcher
│
├── scrapers/
│   ├── prospect_scraper.py      ← GoogleSearchScraper + EmailExtractor + LeadScraper (orchestrator)
│   ├── apollo_scraper.py        ← Apollo firmographic search
│   ├── github_scraper.py        ← GitHub technical-founder search
│   ├── producthunt_scraper.py   ← ProductHunt launcher search
│   └── linkedin_scraper.py      ← Playwright LinkedIn scraper
│
├── whatsapp/
│   └── whatsapp_api.py      ← 360dialog WhatsApp Business API client (HMAC webhook auth, idempotency)
├── whatsapp_bot.py          ← Playwright WhatsApp Web bot (fallback provider)
│
├── tracking/
│   ├── tracker.py           ← HMAC-signed pixel URL builder
│   └── server.py            ← aiohttp tracking pixel server (per-IP rate limit)
│
├── scoring/
│   └── icp_scorer.py        ← Ideal Customer Profile scoring with signal deltas & tiering
├── scheduling/
│   └── timezone_scheduler.py  ← Optimal send windows by timezone, holiday-aware
├── language/
│   └── lang_handler.py      ← AI-powered localization
├── compliance/
│   └── compliance_handler.py  ← CAN-SPAM/GDPR footer, opt-out detection, suppression list
├── reports/
│   └── daily_summary.py     ← Aggregates daily stats, sends WhatsApp report
├── analytics.py             ← Chart generation (matplotlib)
│
└── utils/
    ├── validators.py        ← email/phone/url validation, normalize_phone, sanitize_lead_data
    ├── rate_limiter.py      ← Token-bucket rate limiter
    ├── proxy_manager.py     ← Proxy rotation
    ├── delays.py            ← Randomized sleep utilities
    └── api_usage.py         ← API quota tracking per source
```

### Data Flow (outreach pipeline)

```
Prospect Discovery → ICP Scoring → Status (hot/warm/cold)
  ├── Hot leads → Immediate booking outreach (Calendly link)
  └── Warm/Cold → Multi-step sequence (timezone-aware scheduling)
        Step 1 (immediate) → Step 2 (+2d) → Step 3 (+2d)
        Each step: AI generates personalized message → compliance footer →
          email (SMTP) or WhatsApp (360dialog API or Playwright bot)
        Inbound replies → AI classification → auto-reply or human alert
```

---

## 3. Key Features

| Category | Feature | Details |
|----------|---------|---------|
| **Discovery** | Multi-source scraping | Google Custom Search, DuckDuckGo, Apollo, GitHub, ProductHunt, LinkedIn |
| **Scoring** | ICP Scorer | Signal-based scoring (0–100) with tiers: Tier 1 (auto-contact), Tier 2 (sequence), Tier 3+ (manual) |
| **Scoring** | Legacy LeadScorer | Industry, employee count, location, email presence, website validity |
| **Outreach** | Email sequences | 3-step AI-generated cold emails with follow-ups, HTML tracking pixel, compliance footer |
| **Outreach** | WhatsApp | 360dialog API (production) or Playwright WhatsApp Web (fallback) |
| **Outreach** | Booking outreach | Immediate Calendly link for hot leads (score >= 60) |
| **Compliance** | CAN-SPAM / GDPR | Physical address footer, opt-out detection, global suppression list, per-region rules |
| **Localization** | Multi-language | AI translates messages to recipient's language based on country |
| **Scheduling** | Timezone-aware | Optimal send windows per channel; holiday-aware; weekend/after-hours blocking |
| **Tracking** | Email open detection | HMAC-SHA256 signed tracking pixels; per-IP rate limit; lead re-scoring on open |
| **AI** | Reply classification | Classifies inbound as: interested, question, not_interested, stop, out_of_office, meeting_booked |
| **AI** | Auto-reply | Generates contextual responses for "question" and "interested" classifications |
| **Reporting** | Daily summary | Aggregated stats sent to owner via WhatsApp at 9 AM |
| **Reporting** | Analytics charts | Matplotlib-generated daily/weekly reports |
| **Reliability** | Atomic sends | Unique index + claim pattern prevents duplicate sends across concurrent processes |
| **Reliability** | Idempotent scheduling | Insert-or-update prevents duplicate sequence rows |

---

## 4. Current Status

### Completed Work

#### Phase 1 — Critical Fixes (merged)
| # | Fix | File(s) |
|---|-----|---------|
| 1.1 | `TRACKING_SECRET` now required at startup (fails fast) | `src/tracking/tracker.py:22-27`, `src/config.py:78` |
| 1.2 | Atomic `log_outreach_and_mark_sent()` — INSERT + UPDATE in one transaction | `src/database.py:203-217` |
| 1.3 | Atomic sequence claiming — `claim_sequence_for_send()` prevents duplicate sends | `src/database.py:188-201` |
| 1.4 | WhatsApp webhook HMAC verification + verify-token challenge | `src/whatsapp/whatsapp_api.py:140-173` |
| 1.5 | Background task tracking for graceful shutdown | `main.py:387-394` |
| 1.6 | Rate-limit state moved to instance attributes in `AIClient` | `src/ai_client.py:15-20` |

#### Phase 2 — Bug Fixes (merged)
| # | Fix | File(s) |
|---|-----|---------|
| 2.1 | Phone normalization for WhatsApp reply matching | `src/utils/validators.py:24-38`, `src/whatsapp/whatsapp_api.py:246-255` |
| 2.2 | Footer detection via patterns instead of bare substring | `src/compliance/compliance_handler.py:77-94` |
| 2.3 | Holiday parsing tolerates multiple JSON formats | `src/scheduling/timezone_scheduler.py:119-162` |
| 2.4 | Parallel enrichment with `asyncio.gather` + `Semaphore(5)` | `src/scrapers/prospect_scraper.py:125-149` |
| 2.5 | Webhook dedup via Meta `message_id` uniqueness | `src/database.py:105`, `src/whatsapp/whatsapp_api.py:200-206` |

#### Repository Polish (merged)
| # | Change | Detail |
|---|--------|--------|
| P | README.md rewritten | Professional structure with badges, architecture diagram, feature table, quick start, config reference |
| P | CONTRIBUTING.md created | Standards for code, tests, commits, PRs |
| P | CODE_OF_CONDUCT.md created | Contributor Covenant v2.1 |
| P | LICENSE created | MIT License |
| P | .gitignore expanded | 40+ exclusion patterns (IDE, coverage, dist, secrets, OS files) |
| P | .env.example cleaned | Sectioned format, all 28+ variables documented |
| P | pyproject.toml modernized | Correct build backend, project URLs, dev/lint extras, pytest + ruff config |
| P | CI/CD pipeline created | GitHub Actions: lint (py_compile + pyflakes), test (pytest), security (secret scan) |
| P | PII sanitized | `config/agency_profile.json` — real name/email/phone/address replaced with placeholders |
| P | Redundant files deleted | `handoff.md`, `start.bat`, `requirements-pinned.txt`, `scripts/agent_workspace.sh`, `WORKSPACES.md` |
| P | `src/__init__.py` created | Proper Python package declaration with `__version__ = "1.5.0"` |

#### v1.5.1 — Sprint 1: Security & Bug Fixes (current)
5 fixes applied:
- **B4**: WhatsApp API `_classify()` fallback changed from `"question"` → `"neutral"` (no auto-reply to STOP when AI is down)
- **S4**: `GLOBAL_COLUMNS` made immutable `frozenset`; `update_lead_global()` sorts columns before SQL construction
- **S6**: Proxy credential stripping in malformed-entry log messages
- **S8/S10**: `html_sanitizer.sanitize_html()` wired into all 4 LLM output paths in `email_generator.py`

#### v1.4.0 — Code Review Hard Pass (merged)
25 fixes covering: SMTP concurrency safety, IMAP leak fix, WhatsApp URL parsing, idempotent scheduling, booking guard, email signature `.format()` fix, phone normalization, classification fallback, unified vocabulary, singleton EmailSender, tracking pixel HMAC, HTML escaping, structured logging, regression tests.

### Known Issues (from Comprehensive Audit Report)

#### Critical / High Severity
| ID | Issue | File | Status | Recommendation |
|----|-------|------|--------|----------------|
| S2 | Owner phone auth uses suffix match (endswith) — allows impersonation | `agent.py:1584` | **Open** | Replace with HMAC-signed commands or PIN verification |
| B2 | `get_unreplied_responses()` ignores `limit` parameter | `src/database.py:317-321` | **Open** | Add `LIMIT ?` to SQL query |
| B3 | `process_pending_emails(sender)` has unused `sender` param — method uses `self.email_sender` | `src/outreach/email_generator.py:177` | **Open** | Remove the parameter from the signature |
| B4 | WhatsApp classification falls back to `"question"` when AI is down — triggers unwanted auto-reply | `src/whatsapp/whatsapp_api.py:224-234` | **Open** | Change default to `"not_interested"` |
| S4 | SQL injection risk via dynamic column names in `update_lead_global()` | `src/database.py:418-422` | **Open** | Add strict allowlist validation |
| S5 | LinkedIn credentials stored in plaintext env vars | `.env.example:43-45` | **Known** | Use LinkedIn official API instead of scraping |
| S6 | Proxy credentials in URL string — risk of log leakage | `src/utils/proxy_manager.py:29-30` | **Open** | Separate credentials from URL |

#### Medium Severity
| ID | Issue | File | Status |
|----|-------|------|--------|
| S8 | HTML escaping incomplete — single quotes not escaped | `src/whatsapp_bot.py`, `src/outreach/email_sender.py` | Open |
| S9 | Tracking server binds `0.0.0.0` by default, no CSP headers | `src/tracking/server.py:41` | Open |
| S10 | LLM output embedded in emails without full sanitization | `src/outreach/email_generator.py:79` | Open |
| S11 | Webhook verify token entropy not validated | `src/whatsapp/whatsapp_api.py:150-151` | Open |
| A1 | Tight coupling: `main.py` and `agent.py` share `build_components()` | `main.py:293-320`, `agent.py` | Open |
| A2 | SQLite write contention under high load | `src/database.py:27-30` | Open — enable WAL mode |
| A6 | WhatsApp Web Playwright has no auto-reconnect | `src/whatsapp_bot.py:53-62` | Open |

#### Low Priority
| ID | Issue | File | Status |
|----|-------|------|--------|
| BP1 | Missing type hints on many public APIs | Multiple files | Open |
| BP2 | Test coverage is thin — ~13 tests total | `tests/` | Open |
| BP3 | Magic numbers throughout codebase | Multiple files | Open |
| A7 | `agent.py` is 1770 lines — monolithic | `agent.py` | Open — planned refactor |

### Current Version: 1.5.0

---

## 5. Configuration

### Required Environment Variables (`.env`)

See `.env.example` for the full list. **At minimum, these must be set:**

| Variable | Purpose |
|----------|---------|
| `TRACKING_SECRET` | HMAC key for tracking pixels (required, no default) |
| `EMAIL_ADDRESS` / `EMAIL_PASSWORD` | SMTP credentials for sending |
| `GROQ_API_KEY` or `GOOGLE_AI_API_KEY` | At least one AI provider |
| `CALENDLY_LINK` | Booking link for hot leads |
| `OWNER_PHONE` | WhatsApp number for daily summaries |

### Optional Environment Variables

| Variable | Purpose |
|----------|---------|
| `WHATSAPP_PROVIDER=api` | Switch from Playwright bot to 360dialog WhatsApp API |
| `D360_API_KEY` | 360dialog API key (required if `WHATSAPP_PROVIDER=api`) |
| `APOLLO_API_KEY` | Apollo lead source |
| `GITHUB_TOKEN` | GitHub API token (anonymous = 60 req/hr) |
| `PRODUCTHUNT_TOKEN` | ProductHunt API token |
| `GDPR_MODE=true` | Enable GDPR-compliant footer text |
| `OUTREACH_LANGUAGE=en` | Force language (default: auto-detect from country) |

### Config Files

| File | Purpose |
|------|---------|
| `config/agency_profile.json` | Agency identity, services, target profile, case studies, email signature |
| `config/global_targeting.json` | ICP targeting: industries, titles, company sizes, min score threshold |
| `config/compliance_rules.json` | Per-region sending rules (countries, restrictions) |
| `config/global_holidays.json` | Country-code keyed holiday calendar for timezone scheduler |

---

## 6. How to Run

### Interactive Mode
```bash
python main.py
# → Presents menu: prospect, email outreach, WhatsApp, views, reports, exit
```

### Cron / CLI Mode
```bash
python main.py --prospect      # Find new leads from all sources
python main.py --linkedin      # LinkedIn-only prospecting
python main.py --outreach      # Send pending email sequences
python main.py --whatsapp      # Send pending WhatsApp sequences
python main.py --responses     # Process & classify email replies
python main.py --report        # Generate analytics report
```

### Autonomous Agent
```bash
python agent.py                # Interactive autonomous mode
python agent.py --auto         # Fully autonomous (no menu)
python agent.py --once         # Run one tick and exit
```

### Database Migration
```bash
python -m src.db.migrate       # Add new columns idempotently
```

---

## 7. Database Schema

### Tables

| Table | Key Columns | Notes |
|-------|-------------|-------|
| `leads` | id, company_name, contact_name, email, phone, phone_normalized, score, status, icp_score, icp_tier, detected_timezone, detected_language, region, funding_stage | Status: `new`/`hot`/`warm`/`cold`/`qualified`/`booking_sent`/`unsubscribed` |
| `sequences` | id, lead_id, channel, step, scheduled_for, sent | UNIQUE(lead_id, channel, step) — idempotent scheduling |
| `outreach` | id, lead_id, channel, subject, body | Audit log of sent messages |
| `email_responses` | id, lead_id, subject, body, classification, replied | Inbound email replies |
| `whatsapp_responses` | id, lead_id, phone, body, classification, message_id | Inbound WhatsApp replies; message_id is UNIQUE |
| `email_opens` | id, lead_id, sequence_id, opened_at | Tracking pixel hits |
| `global_unsubscribe` | id, email, phone, unsubscribed_at, reason | Suppression list checked before every send |

### Indexes

| Index | Table | Columns |
|-------|-------|---------|
| `idx_leads_status` | leads | status |
| `idx_leads_score` | leads | score |
| `idx_leads_email` | leads | email |
| `uniq_seq_lead_channel_step` | sequences | lead_id, channel, step (UNIQUE) |
| `idx_wa_resp_msg` | whatsapp_responses | message_id (UNIQUE) |
| `idx_opens_lead` | email_opens | lead_id |
| `idx_unsub_email` | global_unsubscribe | email |
| `idx_unsub_phone` | global_unsubscribe | phone |

---

## 8. Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run regression tests only
python -m pytest tests/test_regressions.py -v

# Compile check (stdlib only, no dependencies)
python -m py_compile src/**/*.py

# Lint with ruff
ruff check .

# Lint with pyflakes
pyflakes src/
```

Current test coverage: ~13 tests in `tests/test_regressions.py` and `tests/test_integration.py`. Core business logic (decision engine, outreach pipeline, WhatsApp messaging) has no dedicated tests.

---

## 9. Branch Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Production-ready code |
| `fix/phase-1-critical` | All completed Phase 1, Phase 2, and repo polish commits (ready for merge to main) |
| `agent/refactor-agent-v2` | Previous major refactor branch (merged) |

---

## 9.5 Strict Commit-and-Push Workflow

**MANDATORY:** Every discrete unit of work — no matter how small — must be committed and pushed immediately. Never accumulate changes across multiple tasks before committing. This rule applies to all developers and AI agents working on this project.

### 9.5.1 The Five-File Update Rule

Every commit that modifies source code, configuration, or behavior **must** update all five of the following files. Skipping any one of them is a violation of project standards.

| # | File | What to update |
|---|------|----------------|
| 1 | `README.md` | Reflect the change in features, configuration, usage examples, architecture diagrams, or badges. If the change is purely internal (refactor with no behavior change), note it in the "Recent Changes" subsection. |
| 2 | `pyproject.toml` | Bump the `version` field using semantic versioning (see §9.5.2). Add any new dependencies to `dependencies` or `optional-dependencies`. Update `classifiers` if the change affects the project's maturity level. |
| 3 | `CHANGELOG.md` | Add a new entry under an unreleased `[Unreleased]` section at the top. Categorize as `### Added`, `### Fixed`, `### Changed`, `### Deprecated`, or `### Removed`. Include file paths and line references where relevant. |
| 4 | `handoff.md` | Update §4 (Current Status) with completed work. Update §10 (Future Development Plans) if the change affects upcoming priorities. Update §13 (Known Gotchas) if the change introduces or resolves a gotcha. |
| 5 | `BUGLOG.md` | Create or append to the bug/glitch log (see §9.5.4 below). Record every bug discovered, glitch observed, or regression encountered — even if not yet fixed. |

### 9.5.2 Semantic Versioning Policy

The project follows [semver](https://semver.org/) strictly. The version lives in two places: `pyproject.toml:version` and `src/__init__.py:__version__`. **Always bump both simultaneously.**

| Bump Type | When to use | Example |
|-----------|-------------|---------|
| **Major** (`2.0.0` → `3.0.0`) | Breaking API changes, schema migrations that lose data, removal of public interfaces | Removing `agent.py` entry point, changing database schema incompatibly |
| **Minor** (`1.5.0` → `1.6.0`) | New features, new modules, new configuration options, new lead sources | Adding a new scraper, adding WhatsApp template support |
| **Patch** (`1.5.0` → `1.5.1`) | Bug fixes, security patches, documentation-only changes, performance improvements | Fixing phone normalization, fixing a crash on startup |

**Version bump procedure:**
```bash
# 1. Edit pyproject.toml
#    version = "1.5.0" → version = "1.5.1"

# 2. Edit src/__init__.py
#    __version__ = "1.5.0" → __version__ = "1.5.1"

# 3. Verify both match
grep 'version =' pyproject.toml
grep '__version__' src/__init__.py
```

### 9.5.3 Commit Message Convention

All commit messages must follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>(<scope>): <description>

[Optional body paragraph explaining context and rationale.]

Refs: #issue-number
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`, `revert`

**Examples:**
```
fix(database): add LIMIT clause to get_unreplied_responses

The method accepted a limit parameter but ignored it in the SQL query,
causing unbounded memory usage on large datasets.

Refs: #B2
```

```
feat(outreach): add Telegram channel support

New TelegramBot class in src/outreach/telegram_bot.py using the
Telegram Bot API. Integrated into OutreachSequence.process_pending().

Refs: #TELE-1
```

```
chore(repo): bump version to 1.5.1

Updates pyproject.toml and src/__init__.py.
Also updates CHANGELOG.md and README.md badges.
```

### 9.5.4 Bug, Glitch & Regression Log (`BUGLOG.md`)

A dedicated file tracks every bug, glitch, regression, and anomaly encountered during development, testing, or production use. This is the project's living issue register.

**Location:** `BUGLOG.md` at the repository root.

**Format:**
```markdown
# Bug & Glitch Log

| Date | ID | Severity | Description | File | Line | Status | Resolution |
|------|----|----------|-------------|------|------|--------|------------|
```

**Severity levels:**
| Level | Meaning |
|-------|---------|
| `CRITICAL` | Data loss, security breach, complete feature failure |
| `HIGH` | Major feature broken, workaround exists but is painful |
| `MEDIUM` | Feature degrades, incorrect output, intermittent failure |
| `LOW` | Cosmetic, minor inconvenience, edge case |
| `INFO` | Observation, no action required |

**Status values:** `OPEN` → `IN_PROGRESS` → `FIXED` → `VERIFIED` → `CLOSED`

**Procedure when discovering a bug:**
1. Log it in `BUGLOG.md` immediately (before any fix attempt)
2. Create a branch: `fix/<short-description>`
3. Fix the bug
4. Add or update tests
5. Update all five files (§9.5.1)
6. Commit with a `fix(...)` message
7. Push and create a PR

**Example entry:**
```markdown
| 2026-07-02 | B2 | HIGH | `get_unreplied_responses()` ignores limit parameter | src/database.py | 317-321 | OPEN | — |
```

### 9.5.5 Pre-Commit Checklist

Before every `git commit`, verify:

- [ ] `py_compile` passes on all modified `.py` files
- [ ] `pyflakes` reports no warnings
- [ ] `pytest` passes (or new tests are added for new behavior)
- [ ] All five files (§9.5.1) are updated
- [ ] Version bumped in both `pyproject.toml` and `src/__init__.py`
- [ ] Commit message follows Conventional Commits format
- [ ] No hardcoded secrets, API keys, or PII in the diff
- [ ] `.env` is NOT staged (verify with `git status`)

### 9.5.6 Push Discipline

- **Never commit locally without pushing.** Every commit must be pushed to `origin` within the same session.
- **Always push to a feature branch**, never directly to `main` (unless you are the sole maintainer and the change is trivial documentation).
- **Create a Pull Request** for every non-trivial change. The PR description must summarize what changed and why, referencing `BUGLOG.md` entries and `CHANGELOG.md` sections.
- **Rebase onto `main`** before merging to keep history linear.

### 9.5.7 AI Agent Specific Instructions

When an AI agent (Claude, or any other) is performing work on this repository:

1. **Complete one discrete unit of work → commit and push → report to user → proceed to next unit.**
2. Do NOT batch multiple unrelated changes into a single commit.
3. Do NOT skip any of the five-file updates.
4. Do NOT defer version bumps until "later."
5. Do NOT accumulate uncommitted changes across turns or sessions.
6. If interrupted mid-task, note the partial state in `BUGLOG.md` with status `IN_PROGRESS`.
7. Upon resumption, check `BUGLOG.md` for abandoned work before starting.

**This is not optional.** Every commit is a complete, self-contained unit of work with full documentation.

---

## 10. Future Development Plans

### Planned (from remediation plan)

#### Phase 3 — Security Hardening
- [ ] Replace owner phone suffix-match auth with full E.164 equality + HMAC commands
- [ ] PII redaction filter for logs (email addresses, phone numbers)
- [ ] Prompt injection prevention for unsanitized user messages
- [ ] Tracking server: default bind to `127.0.0.1`, add security headers

#### Phase 4 — Architecture Improvements
- [ ] Wire `src/config.py` `Settings` into all modules (currently exists but is never imported — 52 `os.getenv` calls scattered)
- [ ] Split `agent.py` (1770 lines) into `src/agent/{scheduler.py, decision_engine.py, monitor.py}`
- [ ] Add missing DB indexes for frequent queries
- [ ] Extract shared classification logic from 4 duplicate implementations into `src/classification/classifier.py`

#### Phase 5 — Test Coverage
- [ ] DecisionEngine unit tests (all 8 normalization mappings, opt-out priority, idempotent re-run, OOO vs auto-reply)
- [ ] Outreach atomicity tests (concurrent claim → one send; suppression skip; footer once)
- [ ] Webhook auth tests (bad signature → 401; duplicate id → one effect; exact phone match)
- [ ] Classifier tests (whitelist enforcement; injection → safe label)
- [ ] Config tests (required raises; type coercion; port extraction)

### Backlog / Nice-to-Have
- [ ] Enable SQLite WAL mode for better concurrent read performance
- [ ] Auto-reconnect watchdog for WhatsApp Web Playwright
- [ ] Health check endpoint on tracking server (`/health`)
- [ ] Persistent IMAP dedup (crash-safe — currently in-memory only)
- [ ] Add `bleach` library for full HTML sanitization of LLM output
- [ ] Migrate to PostgreSQL for write-heavy workloads
- [ ] Add mypy strict type checking to CI

---

## 11. Important Code Patterns & Conventions

### Atomic Sequence Claiming
```python
# Always use this pattern for concurrent send safety:
if not await db.claim_sequence_for_send(seq_id):
    continue  # Another process already claimed it
# ... send message ...
await db.log_outreach_and_mark_sent(lead_id, channel, subject, body, seq_id)
```

### Phone Normalization
```python
from src.utils.validators import normalize_phone
# Always normalize before DB storage and before lookup:
norm = normalize_phone(phone)  # strips +, spaces, dashes; drops leading 00
# Match on equality, never LIKE:
cursor = await db.db.execute("SELECT id FROM leads WHERE phone_normalized = ?", (norm,))
```

### Compliance Footer
```python
# The footer is appended automatically if not already present:
body = compliance.ensure_email_compliant(body, country_code)
# Check FOOTER_PATTERNS, not bare "unsubscribe" substring
```

### WhatsApp Webhook Auth
```python
# GET: verify hub.verify_token
# POST: verify X-Hub-Signature-256 HMAC
# Both reject with 401/403 on failure
```

### Tracking Pixel
```python
from src.tracking.tracker import tracking_pixel_html, verify_signature
# Build URL with HMAC signature
pixel = tracking_pixel_html(lead_id, sequence_id)
# Server validates signature before recording open
assert verify_signature(lead_id, sequence_id, signature)
```

---

## 12. File Locations for Common Tasks

| Task | Primary File(s) |
|------|-----------------|
| Add new lead source | `src/scrapers/prospect_scraper.py` (add to `find_global_prospects`) |
| Modify outreach messages | `src/outreach/email_generator.py` (MessageGenerator prompts) |
| Change scheduling windows | `src/scheduling/timezone_scheduler.py` (CHANNEL_WINDOWS) |
| Add compliance rules | `config/compliance_rules.json` |
| Modify DB schema | `src/database.py` (_create_tables) + `src/db/migrate.py` (migration) |
| Adjust AI models | `src/config.py` (Settings defaults) or env vars |
| Modify autonomous agent | `agent.py` (DecisionEngine, AgentMonitor, TaskScheduler) |
| WhatsApp provider config | `src/whatsapp/whatsapp_api.py` (360dialog) or `src/whatsapp_bot.py` (Playwright) |
| Email credentials | `.env` (EMAIL_ADDRESS, EMAIL_PASSWORD) |
| Tracking pixel | `src/tracking/tracker.py` (builder) + `src/tracking/server.py` (receiver) |

---

## 13. Known Gotchas

1. **`src/config.py` Settings is never imported** — 52 `os.getenv()` calls are scattered across modules. The `Settings` dataclass exists and is correct, but nobody uses it yet. This is Phase 4 work.

2. **`agent.py` and `main.py` share `build_components()`** — changing one breaks the other. They also duplicate the same component construction logic.

3. **WhatsApp Web is fragile** — Playwright-based bot loses session on browser updates, requires manual QR re-scan. The 360dialog API (`WHATSAPP_PROVIDER=api`) is more reliable but costs money.

4. **EmailSender is a singleton** — `main.py` creates one and shares it. If you instantiate a second `EmailSender()`, you'll get a second SMTP connection.

5. **`process_pending_emails(sender)` signature mismatch** — the method takes a `sender` parameter but never receives it from callers. It uses `self.email_sender` internally. The parameter is dead code (see audit B3).

6. **Tracking pixel URL contains `lead_id` and `sequence_id` in plaintext** — while the HMAC signature prevents forgery, the IDs themselves are visible. This is acceptable for the current threat model.

7. **`data/` directory is gitignored** — the SQLite database, WhatsApp sessions, LinkedIn cookies, and reports all live here. Back up `data/` if migrating machines.

8. **Holiday JSON format varies** — the parser tolerates ISO strings, date objects, datetime objects, integer YYYYMMDD, and `{"date": ..., "name": ...}` dicts. But the file must exist at `config/global_holidays.json` or holiday skipping is silently disabled.

---

## 14. Quick Start for New Developer

```bash
# 1. Clone and setup
git clone <repo>
cd lead-gen-agent
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env — set at minimum: TRACKING_SECRET, GROQ_API_KEY, EMAIL_ADDRESS, EMAIL_PASSWORD, CALENDLY_LINK, OWNER_PHONE

# 3. Verify
python -m py_compile main.py
python -m pytest tests/ -v

# 4. Run
python main.py
```

---

## 15. License & Legal

- **License:** MIT (see [LICENSE](LICENSE))
- **Copyright:** TheSpideyBro (2026)
- **Disclaimer:** This tool automates outreach. Users are responsible for compliance with applicable laws (CAN-SPAM, GDPR, TCPA, WhatsApp Terms of Service). The `GDPR_MODE` flag adds required legal notices but does not replace legal counsel.
