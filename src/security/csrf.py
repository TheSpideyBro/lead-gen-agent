"""CSRF Protection - Prevents Cross-Site Request Forgery attacks.

Adds CSRF token validation to all web endpoints.

Usage:
    from src.security.csrf import CSRFProtection
    csrf = CSRFProtection(secret_key="your-secret")
    
    # In handler
    if not csrf.validate_token(request, token):
        return web.Response(status=403)
"""
import hashlib
import hmac
import logging
import os
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class CSRFProtection:
    """Provides CSRF token generation and validation."""
    
    def __init__(self, secret_key: str = None, token_expiry: int = 3600):
        """Initialize CSRF protection.
        
        Args:
            secret_key: Secret key for token signing
            token_expiry: Token expiry time in seconds (default: 1 hour)
        """
        self.secret_key = secret_key or os.getenv("CSRF_SECRET", "default-change-me")
        self.token_expiry = token_expiry
        self._used_tokens: Dict[str, float] = {}  # token -> timestamp
    
    def generate_token(self, user_id: str = None) -> str:
        """Generate a CSRF token.
        
        Args:
            user_id: Optional user identifier
            
        Returns:
            CSRF token string
        """
        timestamp = str(time.time())
        message = f"{timestamp}{user_id or ''}{self.secret_key}"
        signature = hmac.new(
            self.secret_key.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        
        token = f"{timestamp}.{signature}"
        return token
    
    def validate_token(self, token: str, user_id: str = None) -> bool:
        """Validate a CSRF token.
        
        Args:
            token: Token to validate
            user_id: Optional user identifier to match
            
        Returns:
            True if token is valid
        """
        if not token or "." not in token:
            return False
        
        try:
            timestamp_str, signature = token.rsplit(".", 1)
            timestamp = float(timestamp_str)
            
            # Check expiry
            if time.time() - timestamp > self.token_expiry:
                logger.warning("CSRF token expired")
                return False
            
            # Check if token was already used (one-time use)
            if token in self._used_tokens:
                logger.warning("CSRF token already used")
                return False
            
            # Verify signature
            message = f"{timestamp_str}{user_id or ''}{self.secret_key}"
            expected = hmac.new(
                self.secret_key.encode(),
                message.encode(),
                hashlib.sha256
            ).hexdigest()
            
            if not hmac.compare_digest(signature, expected):
                logger.warning("CSRF signature mismatch")
                return False
            
            # Mark token as used
            self._used_tokens[token] = time.time()
            
            # Clean old tokens
            self._cleanup_tokens()
            
            return True
            
        except Exception as e:
            logger.error(f"CSRF validation error: {e}")
            return False
    
    def _cleanup_tokens(self):
        """Remove expired tokens from cache."""
        now = time.time()
        expired = [t for t, ts in self._used_tokens.items() if now - ts > self.token_expiry * 2]
        for t in expired:
            del self._used_tokens[t]


# Global singleton
csrf_protection = CSRFProtection()


def generate_csrf_token(user_id: str = None) -> str:
    """Convenience function to generate CSRF token."""
    return csrf_protection.generate_token(user_id)


def validate_csrf_token(token: str, user_id: str = None) -> bool:
    """Convenience function to validate CSRF token."""
    return csrf_protection.validate_token(token, user_id)
