# Changelog

All notable changes to this project will be documented in this file.

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