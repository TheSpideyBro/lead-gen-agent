"""PII Redactor - Protects sensitive data in logs and output.

Redacts:
- Email addresses
- Phone numbers
- API keys
- Credit card numbers
- IP addresses (optional)

Usage:
    from src.security.pii_redactor import PIIRedactor
    redactor = PIIRedactor()
    safe_text = redactor.redact("Contact john@example.com at +1234567890")
"""
import logging
import re
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class PIIRedactor:
    """Redacts personally identifiable information from text."""
    
    # Patterns for PII detection
    PATTERNS: Dict[str, re.Pattern] = {
        "email": re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'),
        "phone": re.compile(r'\b(?:\+?\d{1,3})?[\s.-]?(?:\(?\d{3}\)?[\s.-]?)?\d{3}[\s.-]?\d{4}\b'),
        "api_key": re.compile(r'(?:api[_-]?key|apikey|token|secret)["\s:=]+["\s]*([a-zA-Z0-9]{20,})["\s]*'),
        "credit_card": re.compile(r'\b(?:\d{4}[\s-]?){3}\d{4}\b'),
        "ip_address": re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
    }
    
    # Replacement strings
    REPLACEMENTS: Dict[str, str] = {
        "email": "[EMAIL_REDACTED]",
        "phone": "[PHONE_REDACTED]",
        "api_key": "[API_KEY_REDACTED]",
        "credit_card": "[CC_REDACTED]",
        "ip_address": "[IP_REDACTED]",
    }
    
    def __init__(self, redact_ips: bool = True):
        """Initialize PII redactor.
        
        Args:
            redact_ips: Whether to redact IP addresses
        """
        self.redact_ips = redact_ips
        self.enabled = True
        
        if not redact_ips:
            del self.PATTERNS["ip_address"]
            del self.REPLACEMENTS["ip_address"]
    
    def redact(self, text: str) -> str:
        """Redact all PII from text.
        
        Args:
            text: Input text that may contain PII
            
        Returns:
            Text with all PII replaced with redaction markers
        """
        if not self.enabled or not text:
            return text
        
        redacted = text
        for pii_type, pattern in self.PATTERNS.items():
            replacement = self.REPLACEMENTS.get(pii_type, f"[{pii_type.upper()}_REDACTED]")
            redacted = pattern.sub(replacement, redacted)
        
        return redacted
    
    def redact_dict(self, data: Dict) -> Dict:
        """Recursively redact PII from dictionary values.
        
        Args:
            data: Dictionary that may contain PII in values
            
        Returns:
            Dictionary with PII redacted
        """
        redacted = {}
        for key, value in data.items():
            if isinstance(value, str):
                redacted[key] = self.redact(value)
            elif isinstance(value, dict):
                redacted[key] = self.redact_dict(value)
            elif isinstance(value, list):
                redacted[key] = [
                    self.redact(item) if isinstance(item, str) else item
                    for item in value
                ]
            else:
                redacted[key] = value
        
        return redacted
    
    def enable(self):
        """Enable PII redaction."""
        self.enabled = True
        logger.info("PII redaction enabled")
    
    def disable(self):
        """Disable PII redaction (not recommended for production)."""
        self.enabled = False
        logger.warning("PII redaction disabled")


# Global singleton for easy import
pii_redactor = PIIRedactor()


def redact_text(text: str) -> str:
    """Convenience function to redact PII from text."""
    return pii_redactor.redact(text)


def redact_dict(data: Dict) -> Dict:
    """Convenience function to redact PII from dictionary."""
    return pii_redactor.redact_dict(data)
