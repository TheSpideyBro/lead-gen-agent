# Bug & Glitch Log

> Living issue register for the Lead Generation Agent project.
> Every bug, glitch, regression, and anomaly encountered during development, testing, or production use is recorded here.
> See [handoff.md §9.5.4](handoff.md) for the logging procedure.

| Date | ID | Severity | Description | File | Line | Status | Resolution |
|------|----|----------|-------------|------|------|--------|------------|
| 2026-07-02 | S2 | CRITICAL | Owner phone auth uses suffix match (endswith) — allows impersonation | `agent.py` | 1584 | OPEN | — |
| 2026-07-02 | B2 | HIGH | `get_unreplied_responses()` ignores `limit` parameter | `src/database.py` | 317-321 | OPEN | — |
| 2026-07-02 | B3 | HIGH | `process_pending_emails(sender)` has unused `sender` param | `src/outreach/email_generator.py` | 177 | OPEN | — |
| 2026-07-12 | B4 | HIGH | WhatsApp classification falls back to `"question"` when AI is down | `src/whatsapp/whatsapp_api.py` | 224-234 | FIXED | 2026-07-12: Changed to `"neutral"` — no auto-reply when AI is down. |
| 2026-07-12 | S4 | HIGH | SQL injection risk via dynamic column names in `update_lead_global()` | `src/database.py` | 418-422 | FIXED | 2026-07-12: `GLOBAL_COLUMNS` is now a `frozenset`; columns sorted before SQL construction. |
| 2026-07-02 | S5 | HIGH | LinkedIn credentials stored in plaintext env vars | `.env.example` | 43-45 | KNOWN | — |
| 2026-07-12 | S6 | HIGH | Proxy credentials in URL string — risk of log leakage | `src/utils/proxy_manager.py` | 29-30 | FIXED | 2026-07-12: Malformed entry log strips credentials via `@` split. |
| 2026-07-12 | S8 | MEDIUM | HTML escaping incomplete — single quotes not escaped | `src/whatsapp_bot.py`, `src/outreach/email_sender.py` | — | FIXED | 2026-07-12: Wired `html_sanitizer.sanitize_html()` into all LLM output paths in `email_generator.py`. Bleach library provides full sanitization when installed; fallback handles common cases. |
| 2026-07-02 | S9 | MEDIUM | Tracking server binds `0.0.0.0` by default, no CSP headers | `src/tracking/server.py` | 41 | OPEN | — |
| 2026-07-12 | S10 | MEDIUM | LLM output embedded in emails without full sanitization | `src/outreach/email_generator.py` | 79 | FIXED | 2026-07-12: All 4 LLM generation paths now pass through `sanitize_html()`. |
| 2026-07-02 | S11 | MEDIUM | Webhook verify token entropy not validated | `src/whatsapp/whatsapp_api.py` | 150-151 | OPEN | — |
| 2026-07-02 | A1 | MEDIUM | Tight coupling: `main.py` and `agent.py` share `build_components()` | `main.py` | 293-320 | OPEN | — |
| 2026-07-02 | A2 | MEDIUM | SQLite write contention under high load | `src/database.py` | 27-30 | OPEN | — |
| 2026-07-02 | A6 | MEDIUM | WhatsApp Web Playwright has no auto-reconnect | `src/whatsapp_bot.py` | 53-62 | OPEN | — |
| 2026-07-02 | BP1 | LOW | Missing type hints on many public APIs | Multiple | — | OPEN | — |
| 2026-07-02 | BP2 | LOW | Test coverage is thin — ~13 tests total | `tests/` | — | OPEN | — |
| 2026-07-02 | BP3 | LOW | Magic numbers throughout codebase | Multiple | — | OPEN | — |
| 2026-07-02 | A7 | LOW | `agent.py` is 1770 lines — monolithic | `agent.py` | — | OPEN | — |
