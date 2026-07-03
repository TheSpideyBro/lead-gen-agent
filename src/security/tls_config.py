"""TLS Configuration - Ensures secure HTTPS connections.

Configures aiohttp sessions with proper TLS verification.

Usage:
    from src.security.tls_config import create_secure_session
    
    async with create_secure_session() as session:
        async with session.get("https://api.example.com") as resp:
            data = await resp.json()
"""
import asyncio
import logging
from typing import Optional

import aiohttp
from aiohttp import TCPConnector

logger = logging.getLogger(__name__)


class TLSConfig:
    """Configures secure TLS settings for HTTP clients."""
    
    def __init__(
        self,
        verify_ssl: bool = True,
        ssl_cert_path: str = None,
        timeout: int = 30,
        max_retries: int = 3,
    ):
        """Initialize TLS configuration.
        
        Args:
            verify_ssl: Whether to verify SSL certificates
            ssl_cert_path: Path to custom CA certificate bundle
            timeout: Request timeout in seconds
            max_retries: Maximum number of retries
        """
        self.verify_ssl = verify_ssl
        self.ssl_cert_path = ssl_cert_path
        self.timeout = timeout
        self.max_retries = max_retries
    
    def get_connector(self) -> TCPConnector:
        """Get a TCP connector with TLS configuration.
        
        Returns:
            Configured TCPConnector instance
        """
        ssl = None
        if self.verify_ssl:
            if self.ssl_cert_path:
                import ssl as ssl_module
                ssl_context = ssl_module.create_default_context(
                    cafile=self.ssl_cert_path
                )
                ssl = ssl_context
                logger.info(f"Using custom CA bundle: {self.ssl_cert_path}")
            else:
                # Use system default CA certificates
                ssl = True
                logger.info("Using system default CA certificates")
        else:
            logger.warning("SSL verification disabled - NOT RECOMMENDED for production")
            ssl = False
        
        return TCPConnector(ssl=ssl)
    
    def get_timeout(self) -> aiohttp.ClientTimeout:
        """Get timeout configuration.
        
        Returns:
            ClientTimeout instance
        """
        return aiohttp.ClientTimeout(
            total=self.timeout,
            connect=10,
            sock_read=15,
            sock_connect=10,
        )
    
    async def create_session(self, **kwargs) -> aiohttp.ClientSession:
        """Create a secure aiohttp session.
        
        Args:
            **kwargs: Additional arguments passed to ClientSession
            
        Returns:
            Configured ClientSession instance
        """
        connector = self.get_connector()
        timeout = self.get_timeout()
        
        return aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            **kwargs,
        )


# Default secure TLS configuration
default_tls_config = TLSConfig(verify_ssl=True)


async def create_secure_session(**kwargs) -> aiohttp.ClientSession:
    """Create a secure aiohttp session with default TLS config.
    
    Args:
        **kwargs: Additional arguments passed to ClientSession
        
    Returns:
        Configured ClientSession instance
    """
    return await default_tls_config.create_session(**kwargs)


def verify_https_url(url: str) -> bool:
    """Verify that a URL uses HTTPS.
    
    Args:
        url: URL to verify
        
    Returns:
        True if URL uses HTTPS
    """
    return url.startswith("https://")
