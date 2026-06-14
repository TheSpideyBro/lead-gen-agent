@echo off
setlocal
cd /d "C:\Users\sadda\Desktop\lead-gen-agent\worktrees\refactor-resolve"

echo === stage all resolved files ===
git add -A
git status --short

echo.
echo === commit the merge resolution ===
git -c user.name="refactor-agent" -c user.email="agent@local" commit -m "merge: resolve agent/refactor-agent into origin/main (P0-P3 + GLOBAL)

Merge commit bringing the v1.4.0 refactor into the post-PR-#1 main
line. The auto-merge handled 11 files; 2 real content conflicts were
resolved manually:

src/outreach/email_generator.py
  - Took origin/main's version (it adds TimezoneScheduler,
    LangHandler, ComplianceHandler for the GLOBAL compliance / i18n /
    timezone features).
  - Surgically re-applied four P0-P1 fixes that the auto-merge had
    dropped: the _BOOKING_GUARD constant + check, the
    email_sender=None injection on __init__, the contact-info guard
    at the top of schedule_sequence, and the _signature() helper
    that uses str.replace() instead of str.format() (the v1.4.0
    P1 fix).
  - Removed 4 unused imports (datetime, timedelta, Dict, List) that
    the auto-merge had reintroduced.

src/whatsapp_bot.py
  - Reverted to my refactor-agent version (main did not touch this
    file; the new WhatsApp code lives in src/whatsapp/whatsapp_api.py
    in origin/main).
  - Brings back: phonenumbers-based normalization, the
    _extract_phone_from_header() helper, _html_escape() on outbound
    bodies, and the unified 'not_interested' classification.

Verified on the merged tree:
  - No conflict markers remaining.
  - python scripts/precommit_check.py -> exit 0
  - python -m pyflakes on the two resolved files -> exit 0
  - python -m unittest tests.test_regressions -> 4/4 pass
  - Full-repo py_compile across all 23 changed/added files -> clean

This commit is local-only; not pushed to GitHub per the operator's
explicit instruction." 2>&1
