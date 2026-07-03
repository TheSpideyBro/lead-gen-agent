"""Log Integrity Checker - Prevents log tampering.

Uses cryptographic hashing to verify log files haven't been modified.
Each log entry includes a hash of the previous entry, creating an immutable chain.

Usage:
    from src.security.log_integrity import LogIntegrityChecker
    checker = LogIntegrityChecker()
    checker.verify_integrity()  # Returns True if logs are untampered
"""
import hashlib
import hmac
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class LogIntegrityChecker:
    """Verifies and maintains integrity of log files."""
    
    def __init__(self, log_path: str = "data/agent_log.jsonl", secret_key: str = None):
        """Initialize log integrity checker.
        
        Args:
            log_path: Path to the log file
            secret_key: HMAC secret key for signing
        """
        self.log_path = Path(log_path)
        self.secret_key = secret_key or hashlib.sha256(
            str(time.time()).encode()
        ).hexdigest()
        self._chain: List[str] = []  # Hash chain
    
    def sign_entry(self, entry: Dict) -> Dict:
        """Add cryptographic signature to a log entry.
        
        Args:
            entry: Log entry dictionary
            
        Returns:
            Entry with signature added
        """
        # Remove existing signature if present
        entry_copy = {k: v for k, v in entry.items() if k != "signature"}
        
        # Create signature
        message = json.dumps(entry_copy, sort_keys=True)
        signature = hmac.new(
            self.secret_key.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        
        entry_copy["signature"] = signature
        entry_copy["signed_at"] = time.time()
        
        return entry_copy
    
    def verify_entry(self, entry: Dict) -> bool:
        """Verify a log entry's signature.
        
        Args:
            entry: Log entry to verify
            
        Returns:
            True if signature is valid
        """
        signature = entry.get("signature")
        if not signature:
            logger.warning("Log entry missing signature")
            return False
        
        # Remove signature and recompute
        entry_copy = {k: v for k, v in entry.items() if k != "signature"}
        message = json.dumps(entry_copy, sort_keys=True)
        expected = hmac.new(
            self.secret_key.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(signature, expected)
    
    def verify_chain(self) -> bool:
        """Verify the entire log file integrity.
        
        Returns:
            True if all entries are valid and chain is intact
        """
        if not self.log_path.exists():
            return True  # No logs to verify
        
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            for i, line in enumerate(lines):
                entry = json.loads(line.strip())
                
                # Verify signature
                if not self.verify_entry(entry):
                    logger.error(f"Log entry {i} has invalid signature")
                    return False
                
                # Verify chain continuity
                if i > 0:
                    prev_hash = lines[i-1].split('"chain_hash": "')[1].split('"')[0]
                    current_hash = entry.get("chain_hash", "")
                    if current_hash != prev_hash:
                        logger.error(f"Log chain broken at entry {i}")
                        return False
            
            logger.info(f"Verified {len(lines)} log entries - chain intact")
            return True
            
        except Exception as e:
            logger.error(f"Log verification failed: {e}")
            return False
    
    def add_chain_hash(self, entry: Dict, prev_hash: str = "") -> Dict:
        """Add chain hash to link entries together.
        
        Args:
            entry: Log entry
            prev_hash: Hash of previous entry
            
        Returns:
            Entry with chain_hash added
        """
        # Create chain hash
        chain_data = f"{prev_hash}{json.dumps(entry, sort_keys=True)}"
        entry["chain_hash"] = hashlib.sha256(chain_data.encode()).hexdigest()
        
        return entry


# Global singleton
log_checker = LogIntegrityChecker()


def sign_log_entry(entry: Dict) -> Dict:
    """Convenience function to sign a log entry."""
    return log_checker.sign_entry(entry)


def verify_log_entry(entry: Dict) -> bool:
    """Convenience function to verify a log entry."""
    return log_checker.verify_entry(entry)


def verify_logs() -> bool:
    """Convenience function to verify entire log file."""
    return log_checker.verify_chain()
