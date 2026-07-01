import re


def validate_email(email: str) -> bool:
    if not email or len(email) > 254:
        return False
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def sanitize_string(value: str, max_length: int = 1000) -> str:
    if value is None:
        return ""
    return str(value)[:max_length].strip()


def validate_phone(phone: str) -> bool:
    if not phone:
        return False
    digits = ''.join(c for c in phone if c.isdigit())
    return 7 <= len(digits) <= 15


def normalize_phone(phone: str) -> str:
    """Reduce a phone string to a canonical digits-only form for matching.

    Strips all non-digit characters (spaces, dashes, parens, leading '+'),
    and drops a single leading international-dialing '00' prefix so that
    '+1 (555) 555-0100', '0015555550100' and '15555550100' all compare equal.
    Returns '' for falsy/garbage input. Use this for BOTH storage and lookup
    so equality holds instead of a fuzzy LIKE suffix match.
    """
    if not phone:
        return ""
    digits = ''.join(c for c in str(phone) if c.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    return digits


def validate_url(url: str) -> bool:
    if not url:
        return False
    pattern = r'^https?://[^\s/$.?#].[^\s]*$'
    return bool(re.match(pattern, url, re.IGNORECASE))


def sanitize_lead_data(lead: dict) -> dict:
    sanitized = {
        "company_name": sanitize_string(lead.get("company_name", "")),
        "contact_name": sanitize_string(lead.get("contact_name")) or None,
        "contact_title": sanitize_string(lead.get("contact_title")) or None,
        "email": sanitize_string(lead.get("email")) or None,
        "phone": sanitize_string(lead.get("phone")) or None,
        "website": sanitize_string(lead.get("website")) or None,
        "industry": sanitize_string(lead.get("industry")) or None,
        "location": sanitize_string(lead.get("location")) or None,
        "employees": lead.get("employees") if isinstance(lead.get("employees"), int) else 0,
        "source": sanitize_string(lead.get("source"), 50) or None,
    }
    return sanitized