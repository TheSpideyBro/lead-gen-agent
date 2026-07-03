"""Network Segmentation Configuration.

Defines network zones and access controls for the lead-gen-agent system.
Used to isolate sensitive components and enforce least-privilege networking.

Zones:
  - dmz: Public-facing services (tracking server, webhook receiver)
  - internal: Application logic (agent, main.py)
  - restricted: Database, secrets storage
  - external: Third-party APIs (SMTP, WhatsApp, AI providers)

Usage:
    from src.security.network import NetworkSegment, get_zone_for_service
    
    # Check if service can communicate
    if get_zone_for_service("tracking") == NetworkSegment.DMZ:
        # Allow public access
        pass
"""
import logging
import os
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class NetworkSegment(Enum):
    """Network segmentation zones."""
    DMZ = "dmz"  # Public-facing
    INTERNAL = "internal"  # Application logic
    RESTRICTED = "restricted"  # Sensitive data
    EXTERNAL = "external"  # Third-party APIs


class NetworkPolicy:
    """Defines network access policies between segments."""
    
    # Default policy: deny all, allow specific
    ALLOWED_COMMUNICATIONS = {
        NetworkSegment.DMZ: {
            NetworkSegment.INTERNAL,
        },
        NetworkSegment.INTERNAL: {
            NetworkSegment.DMZ,
            NetworkSegment.RESTRICTED,
            NetworkSegment.EXTERNAL,
        },
        NetworkSegment.RESTRICTED: set(),  # No outbound
        NetworkSegment.EXTERNAL: set(),  # No inbound
    }
    
    # Service to zone mapping
    SERVICE_ZONES: Dict[str, NetworkSegment] = {
        "tracking_server": NetworkSegment.DMZ,
        "webhook_receiver": NetworkSegment.DMZ,
        "agent": NetworkSegment.INTERNAL,
        "main": NetworkSegment.INTERNAL,
        "database": NetworkSegment.RESTRICTED,
        "secrets_manager": NetworkSegment.RESTRICTED,
        "email_sender": NetworkSegment.EXTERNAL,
        "whatsapp_client": NetworkSegment.EXTERNAL,
        "ai_client": NetworkSegment.EXTERNAL,
    }
    
    @classmethod
    def can_communicate(cls, from_service: str, to_service: str) -> bool:
        """Check if two services can communicate.
        
        Args:
            from_service: Source service name
            to_service: Destination service name
            
        Returns:
            True if communication is allowed
        """
        from_zone = cls.SERVICE_ZONES.get(from_service)
        to_zone = cls.SERVICE_ZONES.get(to_service)
        
        if not from_zone or not to_zone:
            logger.warning(f"Unknown service zones: {from_service} -> {to_service}")
            return False
        
        allowed_targets = cls.ALLOWED_COMMUNICATIONS.get(from_zone, set())
        return to_zone in allowed_targets
    
    @classmethod
    def get_zone_for_service(cls, service: str) -> Optional[NetworkSegment]:
        """Get the network zone for a service.
        
        Args:
            service: Service name
            
        Returns:
            Network zone or None if unknown
        """
        return cls.SERVICE_ZONES.get(service)
    
    @classmethod
    def enforce_network_policy(cls) -> bool:
        """Enforce network segmentation policies.
        
        Returns:
            True if policy is enforced
        """
        # In production, this would configure firewall rules
        # For now, just log the policy
        logger.info("Network segmentation policy loaded")
        logger.info(f"Defined {len(cls.SERVICE_ZONES)} services across {len(NetworkSegment)} zones")
        return True


# Bind tracking server to localhost only
TRACKING_HOST = os.getenv("TRACKING_HOST", "127.0.0.1")
TRACKING_PORT = int(os.getenv("TRACKING_PORT", "8080"))

# Webhook receiver binds to internal network only
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "127.0.0.1")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8081"))

# Database binds to localhost
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "5432"))  # PostgreSQL default

# Secrets manager access
SECRETS_MANAGER_HOST = os.getenv("SECRETS_MANAGER_HOST", "127.0.0.1")
SECRETS_MANAGER_PORT = int(os.getenv("SECRETS_MANAGER_PORT", "8200"))  # Vault default

logger.info(f"Network configuration loaded:")
logger.info(f"  Tracking server: {TRACKING_HOST}:{TRACKING_PORT}")
logger.info(f"  Webhook receiver: {WEBHOOK_HOST}:{WEBHOOK_PORT}")
logger.info(f"  Database: {DB_HOST}:{DB_PORT}")
logger.info(f"  Secrets manager: {SECRETS_MANAGER_HOST}:{SECRETS_MANAGER_PORT}")
