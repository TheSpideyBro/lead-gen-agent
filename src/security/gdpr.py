"""GDPR Data Retention - Manages data lifecycle for GDPR compliance.

Implements:
- Automatic data expiration
- Right to erasure (delete all user data)
- Data export functionality
- Retention policy enforcement

Usage:
    from src.security.gdpr import GDPRDataController
    controller = GDPRDataController(db)
    
    # Delete all data for a lead
    await controller.erase_data(lead_id)
    
    # Export all data for a lead
    data = await controller.export_data(lead_id)
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class GDPRDataController:
    """Manages GDPR compliance for data retention and deletion."""
    
    # Default retention periods (in days)
    DEFAULT_RETENTION = {
        "leads": 730,  # 2 years
        "emails": 365,  # 1 year
        "whatsapp": 365,  # 1 year
        "responses": 180,  # 6 months
        "sequences": 365,  # 1 year
        "opens": 90,  # 3 months
    }
    
    def __init__(self, db, retention_policy: Dict[str, int] = None):
        """Initialize GDPR data controller.
        
        Args:
            db: Database instance
            retention_policy: Custom retention periods in days
        """
        self.db = db
        self.retention_policy = retention_policy or self.DEFAULT_RETENTION
        self.export_dir = Path("data/gdpr_exports")
        self.export_dir.mkdir(parents=True, exist_ok=True)
    
    async def erase_data(self, lead_id: int, reason: str = "user_request") -> bool:
        """Erase all data for a specific lead.
        
        Args:
            lead_id: Lead ID to erase
            reason: Reason for erasure
            
        Returns:
            True if successful
        """
        logger.info(f"Erasuring data for lead {lead_id} (reason: {reason})")
        
        try:
            # Delete from leads table
            await self.db.db.execute(
                "DELETE FROM leads WHERE id = ?",
                (lead_id,)
            )
            
            # Delete related records
            await self.db.db.execute(
                "DELETE FROM outreach WHERE lead_id = ?",
                (lead_id,)
            )
            await self.db.db.execute(
                "DELETE FROM sequences WHERE lead_id = ?",
                (lead_id,)
            )
            await self.db.db.execute(
                "DELETE FROM email_responses WHERE lead_id = ?",
                (lead_id,)
            )
            await self.db.db.execute(
                "DELETE FROM email_opens WHERE lead_id = ?",
                (lead_id,)
            )
            
            await self.db.db.commit()
            logger.info(f"Successfully erased data for lead {lead_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to erase data for lead {lead_id}: {e}")
            await self.db.db.rollback()
            return False
    
    async def erase_data_by_email(self, email: str, reason: str = "user_request") -> int:
        """Erase all data for a specific email address.
        
        Args:
            email: Email address to erase
            reason: Reason for erasure
            
        Returns:
            Number of records deleted
        """
        logger.info(f"Erasuring data for email {email} (reason: {reason})")
        
        # Find all leads with this email
        cursor = await self.db.db.execute(
            "SELECT id FROM leads WHERE email = ?",
            (email,)
        )
        leads = await cursor.fetchall()
        
        deleted = 0
        for lead in leads:
            if await self.erase_data(lead[0], reason):
                deleted += 1
        
        return deleted
    
    async def export_data(self, lead_id: int) -> Optional[str]:
        """Export all data for a specific lead.
        
        Args:
            lead_id: Lead ID to export
            
        Returns:
            Path to exported JSON file, or None if failed
        """
        logger.info(f"Exporting data for lead {lead_id}")
        
        try:
            # Get lead data
            lead = await self.db.get_lead_by_id(lead_id)
            if not lead:
                return None
            
            # Get related data
            cursor = await self.db.db.execute(
                "SELECT * FROM outreach WHERE lead_id = ?",
                (lead_id,)
            )
            outreach = await cursor.fetchall()
            
            cursor = await self.db.db.execute(
                "SELECT * FROM sequences WHERE lead_id = ?",
                (lead_id,)
            )
            sequences = await cursor.fetchall()
            
            # Create export
            export_data = {
                "lead": lead,
                "outreach": outreach,
                "sequences": sequences,
                "exported_at": datetime.now().isoformat(),
                "lead_id": lead_id,
            }
            
            # Save to file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"lead_{lead_id}_{timestamp}.json"
            filepath = self.export_dir / filename
            
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2, default=str)
            
            logger.info(f"Data exported to {filepath}")
            return str(filepath)
            
        except Exception as e:
            logger.error(f"Failed to export data for lead {lead_id}: {e}")
            return None
    
    async def enforce_retention_policies(self) -> Dict[str, int]:
        """Enforce data retention policies.
        
        Returns:
            Dictionary of deleted counts by table
        """
        logger.info("Enforcing data retention policies")
        
        deleted = {}
        now = datetime.now()
        
        for table, days in self.retention_policy.items():
            cutoff = (now - timedelta(days=days)).isoformat()
            
            try:
                cursor = await self.db.db.execute(
                    f"DELETE FROM {table} WHERE created_at < ?",
                    (cutoff,)
                )
                deleted[table] = cursor.rowcount
            except Exception as e:
                logger.error(f"Failed to enforce retention for {table}: {e}")
                deleted[table] = 0
        
        await self.db.db.commit()
        logger.info(f"Retention policies enforced: {deleted}")
        return deleted
    
    async def anonymize_data(self, lead_id: int) -> bool:
        """Anonymize lead data instead of deleting.
        
        Keeps analytics data but removes PII.
        
        Args:
            lead_id: Lead ID to anonymize
            
        Returns:
            True if successful
        """
        logger.info(f"Anonymizing data for lead {lead_id}")
        
        try:
            await self.db.db.execute(
                """UPDATE leads 
                   SET contact_name = 'Anonymized',
                       email = 'anonymized@example.com',
                       phone = '0000000000',
                       notes = COALESCE(notes || ' ', '') || 'Anonymized on ' || CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (lead_id,)
            )
            
            await self.db.db.commit()
            logger.info(f"Successfully anonymized data for lead {lead_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to anonymize data for lead {lead_id}: {e}")
            await self.db.db.rollback()
            return False


# Global singleton
gdpr_controller: Optional[GDPRDataController] = None


def get_gdpr_controller(db) -> GDPRDataController:
    """Get or create GDPR data controller."""
    global gdpr_controller
    if gdpr_controller is None or gdpr_controller.db != db:
        gdpr_controller = GDPRDataController(db)
    return gdpr_controller
