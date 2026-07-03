"""HTML Sanitizer - Sanitizes HTML output to prevent XSS attacks.

Uses bleach library for safe HTML cleaning. Falls back to manual sanitization
if bleach is not installed.

Usage:
    from src.security.html_sanitizer import HTMLSanitizer
    sanitizer = HTMLSanitizer()
    safe_html = sanitizer.sanitize("<script>alert('xss')</script>Hello")
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import bleach
    HAS_BLEACH = True
except ImportError:
    HAS_BLEACH = False
    logger.warning("bleach not installed - using fallback sanitizer")


class HTMLSanitizer:
    """Sanitizes HTML to prevent XSS attacks."""
    
    # Allowed HTML tags
    ALLOWED_TAGS = [
        "b", "i", "u", "em", "strong", "a", "p", "br",
        "ul", "ol", "li", "h1", "h2", "h3", "span", "div"
    ]
    
    # Allowed attributes
    ALLOWED_ATTRS = {
        "a": ["href", "title", "target"],
    }
    
    # Allowed protocols for links
    ALLOWED_PROTOCOLS = ["http", "https", "mailto"]
    
    def __init__(self, use_bleach: bool = None):
        """Initialize HTML sanitizer.
        
        Args:
            use_bleach: Force use of bleach library (defaults to auto-detect)
        """
        self.use_bleach = use_bleach if use_bleach is not None else HAS_BLEACH
        
        if self.use_bleach and not HAS_BLEACH:
            logger.warning("Requested bleach but not installed - falling back")
            self.use_bleach = False
    
    def sanitize(self, html: str, max_length: int = 10000) -> str:
        """Sanitize HTML content.
        
        Args:
            html: Input HTML string
            max_length: Maximum allowed length
            
        Returns:
            Sanitized HTML string
        """
        if not html:
            return ""
        
        # Truncate if too long
        if len(html) > max_length:
            html = html[:max_length]
            logger.warning("HTML content truncated to %d characters", max_length)
        
        if self.use_bleach:
            return self._sanitize_with_bleach(html)
        else:
            return self._sanitize_manual(html)
    
    def _sanitize_with_bleach(self, html: str) -> str:
        """Sanitize using bleach library."""
        try:
            cleaned = bleach.clean(
                html,
                tags=self.ALLOWED_TAGS,
                attributes=self.ALLOWED_ATTRS,
                protocols=self.ALLOWED_PROTOCOLS,
                strip=True
            )
            return cleaned
        except Exception as e:
            logger.error(f"Bleach sanitization failed: {e}")
            return self._sanitize_manual(html)
    
    def _sanitize_manual(self, html: str) -> str:
        """Manual HTML sanitization fallback."""
        # Remove script tags
        html = self._remove_tags(html, "script")
        html = self._remove_tags(html, "iframe")
        html = self._remove_tags(html, "object")
        html = self._remove_tags(html, "embed")
        
        # Remove event handlers
        html = self._remove_attributes(html, [
            "onclick", "onload", "onerror", "onmouseover",
            "onfocus", "onblur", "onsubmit", "onchange"
        ])
        
        # Remove javascript: protocol
        html = html.replace("javascript:", "")
        html = html.replace("vbscript:", "")
        
        return html
    
    def _remove_tags(self, html: str, tag: str) -> str:
        """Remove HTML tags."""
        import re
        pattern = re.compile(rf'<{tag}[^>]*>.*?</{tag}>', re.IGNORECASE | re.DOTALL)
        return pattern.sub('', html)
    
    def _remove_attributes(self, html: str, attrs: list) -> str:
        """Remove HTML attributes."""
        import re
        for attr in attrs:
            pattern = re.compile(rf'\b{attr}\s*=\s*["\'][^"\']*["\']', re.IGNORECASE)
            html = pattern.sub('', html)
        return html
    
    def sanitize_email_body(self, body: str) -> str:
        """Sanitize email body content.
        
        Args:
            body: Email body text
            
        Returns:
            Sanitized body text
        """
        # For plain text emails, just escape HTML entities
        return self.sanitize(body, max_length=50000)


# Global singleton
html_sanitizer = HTMLSanitizer()


def sanitize_html(html: str) -> str:
    """Convenience function to sanitize HTML."""
    return html_sanitizer.sanitize(html)


def sanitize_email(body: str) -> str:
    """Convenience function to sanitize email body."""
    return html_sanitizer.sanitize_email_body(body)
