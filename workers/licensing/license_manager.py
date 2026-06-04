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
ACTIVATION_SERVER = "https://sentinelprime.org/api/activate"
GRACE_PERIOD_DAYS = 7
BETA_GRACE_PERIOD_DAYS = 3

# Routes always allowed in restricted mode (beta expired)
RESTRICTED_ALLOW_PREFIXES = (
    "/license/",
    "/api/trial/",
    "/api/updates/",
    "/api/version",
    "/api/health/",
    "/api/status",
)


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

        # Initialise cache BEFORE load_license() — load_license() calls
        # get_machine_id() which reads self._machine_id_cache.
        self._machine_id_cache = None
        self.license = self.load_license()

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
            "beta_expires_at": None,
            "subscription_valid": False,
            "remote_features_disabled": [],
            "offline_cache": {},
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

    @staticmethod
    def _install_id() -> str:
        try:
            from workers.telemetry.product_analytics import get_install_id
            return get_install_id()
        except Exception:
            return ""

    def get_machine_id(self) -> str:
        """Generate stable machine ID"""
        if self._machine_id_cache:
            return self._machine_id_cache

        # Never use os.getlogin() — it can block indefinitely on Windows services/GUI shells.
        username = (
            os.environ.get("USERNAME")
            or os.environ.get("USER")
            or "unknown"
        )

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
        install_id = self._install_id()

        # Activate key with server
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    ACTIVATION_SERVER,
                    json={"code": key, "machine_id": machine_id, "install_id": install_id},
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
                        self.license['subscription_valid'] = bool(data.get('subscription_valid', True))
                        self.license['restricted_mode'] = False
                        self.apply_remote_policy(data.get('policy') or data)
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

    def check_limit(self, limit_name: str) -> Dict[str, Any]:
        """Check if usage limit is available"""
        if self.is_restricted_mode():
            return {
                "allowed": False,
                "remaining": 0,
                "reason": "restricted_mode",
                "message": "Beta period ended. Activate your license to continue.",
            }
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

    def is_restricted_mode(self) -> bool:
        """Beta expired or remote disable without valid subscription — non-destructive lock."""
        if self.is_pro() and self.subscription_valid():
            return False
        try:
            import build_info as bi
            if getattr(bi, "OWNER_MODE", False):
                return False
            build_type = getattr(bi, "BUILD_TYPE", "dev")
            if build_type not in ("beta", "consumer"):
                return False
        except ImportError:
            return False
        if self.beta_expired():
            return True
        if self.license.get("restricted_mode"):
            return True
        return False

    def beta_expired(self) -> bool:
        expires = self.license.get("beta_expires_at")
        if not expires:
            try:
                import build_info as bi
                if getattr(bi, "BUILD_TYPE", "") != "beta":
                    return False
                days = int(getattr(bi, "TRIAL_DAYS", 7) or 7)
                activated = self.license.get("beta_started_at")
                if not activated:
                    return False
                start = datetime.fromisoformat(activated.replace("Z", ""))
                if datetime.utcnow() > start + timedelta(days=days):
                    return True
                return False
            except Exception:
                return False
        try:
            return datetime.utcnow() > datetime.fromisoformat(expires.replace("Z", ""))
        except Exception:
            return False

    def subscription_valid(self) -> bool:
        if self.license.get("subscription_valid"):
            return True
        return self.is_pro() and bool(self.validate_pro_offline())

    def start_beta_period(self) -> None:
        if self.license.get("beta_started_at"):
            return
        self.license["beta_started_at"] = datetime.utcnow().isoformat()
        try:
            import build_info as bi
            days = int(getattr(bi, "TRIAL_DAYS", 14) or 14)
            self.license["beta_expires_at"] = (
                datetime.utcnow() + timedelta(days=days)
            ).isoformat()
        except Exception:
            pass
        self.save_license(self.license)

    def check_feature(self, feature_name: str) -> Dict[str, Any]:
        """Check if feature is allowed for current tier"""
        disabled = self.license.get("remote_features_disabled") or []
        if feature_name in disabled:
            return {
                "allowed": False,
                "reason": "remote_disabled",
                "message": "This feature is disabled for your account. Contact support.",
            }
        if self.is_restricted_mode():
            return {
                "allowed": False,
                "reason": "restricted_mode",
                "message": "Beta period ended. Activate your license to continue.",
            }
        if self.is_pro():
            return {"allowed": True}

        if feature_name in PRO_FEATURES:
            return {
                "allowed": False,
                "reason": "pro_required",
                "message": "This feature requires SentinelAI Pro. Activate your license key to unlock it.",
            }

        return {"allowed": True}

    def apply_remote_policy(self, payload: Dict[str, Any]) -> None:
        """Apply server policy without deleting local data."""
        cache = dict(self.license.get("offline_cache") or {})
        cache["last_policy"] = payload
        cache["fetched_at"] = datetime.utcnow().isoformat()
        self.license["offline_cache"] = cache
        if "beta_expires_at" in payload:
            self.license["beta_expires_at"] = payload["beta_expires_at"]
        if "features_disabled" in payload:
            self.license["remote_features_disabled"] = list(payload["features_disabled"])
        if payload.get("restricted_mode") is True:
            self.license["restricted_mode"] = True
        elif payload.get("restricted_mode") is False:
            self.license["restricted_mode"] = False
        if payload.get("subscription_valid") is True:
            self.license["subscription_valid"] = True
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
            "restricted_mode": self.is_restricted_mode(),
            "beta_expires_at": self.license.get("beta_expires_at"),
            "beta_expired": self.beta_expired(),
            "subscription_valid": self.subscription_valid(),
            "remote_features_disabled": self.license.get("remote_features_disabled", []),
        }

    def revalidate(self) -> bool:
        """Ping validation server to refresh last_validated_at. Returns True on success."""
        key = self.license.get('key')
        if not key or not self.is_pro():
            return False
        machine_id = self.get_machine_id()
        install_id = self._install_id()
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    VALIDATION_SERVER,
                    json={"key": key, "machine_id": machine_id, "install_id": install_id},
                    follow_redirects=True,
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get('valid'):
                        self.license['last_validated_at'] = datetime.utcnow().isoformat()
                        self.license['subscription_valid'] = bool(data.get('subscription_valid', True))
                        policy = data.get('policy') or data
                        self.apply_remote_policy(policy)
                        self.save_license(self.license)
                        logger.info("License revalidated successfully")
                        return True
                else:
                    logger.warning("License revalidation rejected — downgrading to free")
                    self.license['tier'] = 'free'
                    self.save_license(self.license)
                    return False
        except Exception as e:
            logger.warning(f"Revalidation server unreachable: {e}")
            return self.validate_pro_offline()

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
