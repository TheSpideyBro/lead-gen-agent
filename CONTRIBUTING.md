# Contributing to Lead Generation Agent

Thank you for your interest in contributing! This document outlines the process and guidelines for contributing to this project.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Submitting a Pull Request](#submitting-a-pull-request)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Documentation](#documentation)
- [Commit Guidelines](#commit-guidelines)

---

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold this code.

---

## Getting Started

1. **Fork** the repository
2. **Clone** your fork:
   ```bash
   git clone https://github.com/<your-username>/lead-gen-agent.git
   cd lead-gen-agent
   ```
3. **Create a branch** for your change:
   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/your-fix-name
   ```
4. **Set up the development environment** (see below).

---

## Development Setup

```bash
# Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Copy and configure environment
copy .env.example .env       # Windows
# cp .env.example .env       # macOS / Linux
# Edit .env with your credentials

# Install development dependencies
pip install pytest pytest-cov pyflakes

# Run tests
python -m pytest tests/ -v
```

---

## Making Changes

### What to Contribute

We welcome contributions in these areas:

- **Bug fixes** — Any issue that causes crashes, incorrect behavior, or data loss
- **New lead sources** — Scrapers for additional prospecting platforms
- **Improvements** — Performance, reliability, or usability enhancements
- **Documentation** — README, inline comments, examples
- **Tests** — New test cases to increase coverage
- **Config examples** — Sample `agency_profile.json`, `compliance_rules.json`

### Before You Code

1. **Check existing issues** — Search for open issues to avoid duplicate work
2. **Open an issue** — For features or significant changes, open an issue first to discuss approach
3. **Read the code** — Understand the existing patterns before writing new code

---

## Coding Standards

### Python Style

- **Python 3.11+** — Use features available in Python 3.11 and above
- **Type hints** — Add type annotations to all function parameters and return values
- **Docstrings** — Every public function and class needs a docstring
- **Line length** — Maximum 100 characters per line
- **Naming** — `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_CASE` for constants

### Example

```python
async def send_email(
    email: str,
    subject: str,
    body: str,
    lead_id: Optional[int] = None,
    sequence_id: Optional[int] = None,
) -> bool:
    """Send a single email with concurrency safety.

    Args:
        email: Recipient email address.
        subject: Email subject line.
        body: HTML-escaped email body.
        lead_id: Optional lead identifier for tracking.
        sequence_id: Optional sequence identifier for dedup.

    Returns:
        True if the email was sent successfully, False otherwise.
    """
    if not validate_email(email):
        logger.warning("Invalid email address: %s", email)
        return False

    async with self._lock:
        try:
            await self._smtp.sendmail(...)
            return True
        except smtplib.SMTPException as exc:
            logger.error("SMTP error: %s", exc)
            return False
```

### File Organization

- Place new modules under the appropriate `src/` subdirectory
- Add corresponding tests under `tests/`
- Update `src/utils/__init__.py` exports when adding new utility functions
- Update the README architecture diagram if adding new top-level modules

---

## Testing

All contributions should include tests:

```bash
# Run all tests
python -m pytest tests/ -v

# Run with coverage report
python -m pytest tests/ --cov=src --cov-report=term-missing

# Run a specific test file
python -m pytest tests/test_integration.py -v
```

### Test Guidelines

- **Unit tests** — Test individual functions and classes in isolation
- **Integration tests** — Test interactions between modules (use a temp database)
- **Regression tests** — Add when fixing bugs to prevent recurrence
- **Mock external services** — Use `unittest.mock` for API calls, SMTP, etc.
- **Keep tests fast** — Tests should run in under 60 seconds total

---

## Documentation

- **README.md** — Update if you change features, configuration, or usage
- **Inline docstrings** — Every public function/class needs a docstring
- **Config files** — Add `_comment` fields explaining purpose and format
- **New environment variables** — Document in README.md Configuration table

---

## Commit Guidelines

Use [conventional commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]
```

### Types

| Type | Meaning |
|------|---------|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation changes |
| `style` | Code style (formatting, semicolons, etc.) |
| `refactor` | Code changes that neither fix bugs nor add features |
| `test` | Adding or updating tests |
| `chore` | Maintenance tasks (deps, config, CI) |
| `ci` | CI/CD changes |

### Examples

```
feat(database): add phone_normalized column for exact phone matching
fix(compliance): use precise footer patterns instead of bare substring
docs(readme): add autonomous mode section with remote control commands
test(integration): add webhook auth verification test
refactor(outreach): extract atomic sequence claiming into database layer
```

---

## Submitting a Pull Request

1. **Push your branch** to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```

2. **Open a Pull Request** from your branch into `main`

3. **Fill in the PR template** (if available) with:
   - What this PR does
   - Related issues
   - Testing done
   - Screenshots (if UI changes)

4. **Ensure CI passes** — All tests must pass before merging

5. **Address review feedback** — Respond to comments and make requested changes

6. **Merge** — Once approved and CI passes, squash-merge your PR

---

## Need Help?

- Open an [issue](https://github.com/TheSpideyBro/lead-gen-agent/issues)
- Check the [README](README.md) for usage documentation
- Review the [CHANGELOG](CHANGELOG.md) for recent changes

Thank you for contributing!
