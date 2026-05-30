"""
License Manager — SentinelAI tier enforcement and feature gating
"""
import os
import json
import hashlib
import socket
import platform
import logging
import httpx
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

CAPABILITY_DESCRIPTION = "Manages SentinelAI license validation and tier enforcement"

FREE_LIMITS = {
    "forge_tasks": 10,
    "web_searches": 20,
    "earn_results": 10,
}

PRO_FEATURES = [
    "wake_word",
    "home_assistant",
    "cameras",
    "telegram",
    "whatsapp",
    "market",
    "health",
    "finance",
    "spotify",
    "packages",
    "upwork_scanner",
    "freelancer_scanner",
    "bugcrowd_scanner",
    "rag",
    "escalation",
    "capability_system",
    "full_earn",
    "full_morning_briefing",
]

VALIDATION_SERVER = "https://sentinelprime.org/api/validate"
GRACE_PERIOD_DAYS = 7


class LicenseManager:
    """Manages SentinelAI licensing and tier enforcement"""

    def __init__(self, license_file_path: Optional[str] = None):
        """Initialize license manager

        Args:
            license_file_path: Path to license.json file. If None, attempts to use
                             LICENSE_FILE_PATH env var or creates in current directory.
        """
        if license_file_path:
            self.license_file_path = license_file_path
        else:
            self.license_file_path = os.getenv(
                'LICENSE_FILE_PATH',
                os.path.join(os.path.expanduser('~'), '.sentinelai', 'license.json')
            )

        # Ensure directory exists
        os.makedirs(os.path.dirname(self.license_file_path), exist_ok=True)

        self.license = self.load_license()
        self._machine_id_cache = None

    def load_license(self) -> Dict[str, Any]:
        """Load license from file, create default if missing"""
        try:
            if os.path.exists(self.license_file_path):
                with open(self.license_file_path, 'r') as f:
                    data = json.load(f)
                    logger.info(f"License loaded from {self.license_file_path}")
                    return data
        except Exception as e:
            logger.warning(f"Failed to load license: {e}")

        # Create default free tier license
        default = {
            "key": None,
            "tier": "free",
            "activated_at": None,
            "machine_id": self.get_machine_id(),
            "last_validated_at": None,
            "usage": {
                "forge_tasks": 0,
                "web_searches": 0,
                "earn_results": 0,
            }
        }

        self.save_license(default)
        logger.info(f"Created default free tier license at {self.license_file_path}")
        return default

    def save_license(self, license_data: Dict[str, Any]) -> None:
        """Save license to file"""
        try:
            os.makedirs(os.path.dirname(self.license_file_path), exist_ok=True)
            with open(self.license_file_path, 'w') as f:
                json.dump(license_data, f, indent=2)
                self.license = license_data
                logger.info("License saved")
        except Exception as e:
            logger.error(f"Failed to save license: {e}")

    def get_machine_id(self) -> str:
        """Generate stable machine ID"""
        if self._machine_id_cache:
            return self._machine_id_cache

        try:
            # Hash username + hostname + CPU info for stable ID
            username = os.getlogin() if hasattr(os, 'getlogin') else 'unknown'
        except:
            username = 'unknown'

        try:
            hostname = socket.gethostname()
        except:
            hostname = 'unknown'

        try:
            processor = platform.processor()
        except:
            processor = 'unknown'

        data = f"{username}{hostname}{processor}"
        machine_id = hashlib.sha256(data.encode()).hexdigest()[:16]
        self._machine_id_cache = machine_id
        return machine_id

    def get_tier(self) -> str:
        """Get current tier (free or pro)"""
        return self.license.get('tier', 'free')

    def is_pro(self) -> bool:
        """Check if pro tier is active"""
        return self.get_tier() == 'pro'

    def activate(self, key: str) -> Dict[str, Any]:
        """Activate pro license with key

        Returns:
            {success: bool, message: str, tier?: str}
        """
        machine_id = self.get_machine_id()

        # Validate key with server
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    VALIDATION_SERVER,
                    json={"key": key, "machine_id": machine_id},
                    follow_redirects=True
                )

                if response.status_code == 200:
                    data = response.json()

                    if data.get('valid'):
                        # Update license
                        self.license['key'] = key
                        self.license['tier'] = 'pro'
                        self.license['machine_id'] = machine_id
                        self.license['activated_at'] = datetime.utcnow().isoformat()
                        self.license['last_validated_at'] = datetime.utcnow().isoformat()
                        self.save_license(self.license)

                        return {
                            "success": True,
                            "message": "Pro activated successfully",
                            "tier": "pro"
                        }
                    else:
                        reason = data.get('reason', 'unknown')
                        if reason == 'already_activated':
                            return {
                                "success": False,
                                "message": "This license key is already activated on another machine"
                            }
                        else:
                            return {
                                "success": False,
                                "message": "Invalid or expired license key"
                            }

        except Exception as e:
            logger.warning(f"Activation server unreachable: {e}")
            return {
                "success": False,
                "message": f"Could not connect to activation server: {str(e)}"
            }

    def deactivate(self) -> Dict[str, Any]:
        """Deactivate pro license and reset to free"""
        self.license['key'] = None
        self.license['tier'] = 'free'
        self.license['activated_at'] = None
        self.license['last_validated_at'] = None
        self.license['usage'] = {
            "forge_tasks": 0,
            "web_searches": 0,
            "earn_results": 0,
        }
        self.save_license(self.license)

        return {
            "success": True,
            "message": "License deactivated, reset to free tier",
            "tier": "free"
        }

    def check_feature(self, feature_name: str) -> Dict[str, Any]:
        """Check if feature is allowed for current tier"""
        if self.is_pro():
            return {"allowed": True}

        if feature_name in PRO_FEATURES:
            return {
                "allowed": False,
                "reason": "pro_required",
                "message": f"This feature requires SentinelAI Pro. Activate your license key to unlock it."
            }

        return {"allowed": True}

    def check_limit(self, limit_name: str) -> Dict[str, Any]:
        """Check if usage limit is available"""
        if self.is_pro():
            return {"allowed": True, "remaining": -1}

        current = self.license.get('usage', {}).get(limit_name, 0)
        max_val = FREE_LIMITS.get(limit_name, 0)

        if max_val == 0:  # No limit defined
            return {"allowed": True, "remaining": -1}

        if current >= max_val:
            feature_name = limit_name.replace('_', ' ')
            return {
                "allowed": False,
                "remaining": 0,
                "reason": "limit_reached",
                "message": f"You've used all {max_val} free {feature_name}. Activate Pro to continue."
            }

        remaining = max_val - current
        return {
            "allowed": True,
            "remaining": remaining
        }

    def increment_usage(self, limit_name: str) -> None:
        """Increment usage counter for free tier users"""
        if self.is_pro():
            return  # No tracking for pro users

        if 'usage' not in self.license:
            self.license['usage'] = {}

        if limit_name not in self.license['usage']:
            self.license['usage'][limit_name] = 0

        self.license['usage'][limit_name] += 1
        self.save_license(self.license)

    def get_status(self) -> Dict[str, Any]:
        """Get license status for API response"""
        return {
            "tier": self.get_tier(),
            "is_pro": self.is_pro(),
            "key": "***" if self.license.get('key') else None,
            "activated_at": self.license.get('activated_at'),
            "machine_id": self.get_machine_id(),
            "usage": self.license.get('usage', {}),
            "limits": FREE_LIMITS if not self.is_pro() else {},
        }

    def validate_pro_offline(self) -> bool:
        """Check if pro license can work offline (within grace period)"""
        if not self.is_pro():
            return False

        last_validated = self.license.get('last_validated_at')
        if not last_validated:
            return False  # Never validated, can't use offline

        try:
            last_time = datetime.fromisoformat(last_validated)
            grace_deadline = last_time + timedelta(days=GRACE_PERIOD_DAYS)

            if datetime.utcnow() < grace_deadline:
                return True  # Still within grace period
            else:
                # Grace period expired, downgrade to free
                logger.warning("Pro license offline grace period expired, downgrading to free")
                self.license['tier'] = 'free'
                self.save_license(self.license)
                return False

        except Exception as e:
            logger.error(f"Error checking grace period: {e}")
            return False


# Global instance
_license_manager = None


def get_license_manager(license_file_path: Optional[str] = None) -> LicenseManager:
    """Get or create global license manager"""
    global _license_manager
    if _license_manager is None:
        _license_manager = LicenseManager(license_file_path)
    return _license_manager
