"""
workers/identity/identity_manager.py
Manages Paul's credentials for Claude.ai and ChatGPT.
Encrypts everything with Fernet + machine-ID derived key.
Handles auto-login on startup.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Storage location
_SENTINEL_DIR = Path.home() / ".sentinelai"
_CREDS_FILE = _SENTINEL_DIR / "identity.enc"


def _derive_key() -> bytes:
    """
    Derive a Fernet key from machine-specific identifiers.
    Stable across reboots, unique per machine.
    """
    try:
        import uuid
        machine_id = str(uuid.getnode())
    except Exception:
        machine_id = "sentinel-default"

    try:
        machine_id += platform.node()
    except Exception:
        pass

    # PBKDF2 to get a 32-byte key, then base64-encode for Fernet
    import base64
    raw = hashlib.pbkdf2_hmac(
        "sha256",
        machine_id.encode(),
        b"SentinelPrimeInc2026",
        100_000,
        dklen=32,
    )
    return base64.urlsafe_b64encode(raw)


def _get_fernet():
    """Return a Fernet instance with the machine-derived key."""
    from cryptography.fernet import Fernet
    key = _derive_key()
    return Fernet(key)


class IdentityManager:
    """
    Manages Paul's credentials for Claude.ai and ChatGPT.
    Encrypts everything with Fernet + machine-ID derived key.
    Never logs credentials. Never stores plaintext.
    """

    CREDENTIALS_FIELDS = [
        "user_name", "user_email",
        "claude_email", "claude_password",
        "claude_2fa_method", "claude_totp_secret",
        "chatgpt_email", "chatgpt_password",
        "chatgpt_2fa_method", "chatgpt_totp_secret",
        "google_email", "google_password",
        "gmail_2fa_enabled", "adb_sms_enabled",
    ]

    def __init__(self):
        _SENTINEL_DIR.mkdir(parents=True, exist_ok=True)

    def save_credentials(self, data: dict) -> bool:
        """Encrypt and save credentials. Returns True on success."""
        try:
            f = _get_fernet()
            # Only store known fields
            clean = {k: data.get(k, "") for k in self.CREDENTIALS_FIELDS}
            encrypted = f.encrypt(json.dumps(clean).encode())
            _CREDS_FILE.write_bytes(encrypted)
            logger.info("[Identity] Credentials saved.")
            return True
        except Exception as e:
            logger.error("[Identity] Failed to save credentials: %s", e)
            return False

    def load_credentials(self) -> Optional[dict]:
        """Decrypt and return credentials. None if not set or decryption fails."""
        if not _CREDS_FILE.exists():
            return None
        try:
            f = _get_fernet()
            raw = f.decrypt(_CREDS_FILE.read_bytes())
            return json.loads(raw.decode())
        except Exception as e:
            logger.warning("[Identity] Failed to load credentials: %s", e)
            return None

    def has_credentials(self) -> bool:
        """True if credentials file exists and decrypts OK."""
        return self.load_credentials() is not None

    def get_user_name(self) -> str:
        """Return Paul's name. Falls back to 'Paul'."""
        creds = self.load_credentials()
        if creds:
            return creds.get("user_name") or "Paul"
        return "Paul"

    def get_user_email(self) -> str:
        creds = self.load_credentials()
        if creds:
            return creds.get("user_email") or ""
        return ""

    def clear_credentials(self):
        """Wipe credentials file. Triggers login screen on next launch."""
        try:
            if _CREDS_FILE.exists():
                _CREDS_FILE.unlink()
            logger.info("[Identity] Credentials cleared.")
        except Exception as e:
            logger.error("[Identity] Failed to clear credentials: %s", e)

    def get_claude_creds(self) -> tuple[str, str]:
        creds = self.load_credentials() or {}
        return creds.get("claude_email", ""), creds.get("claude_password", "")

    def get_chatgpt_creds(self) -> tuple[str, str]:
        creds = self.load_credentials() or {}
        return creds.get("chatgpt_email", ""), creds.get("chatgpt_password", "")

    def get_google_creds(self) -> tuple[str, str]:
        creds = self.load_credentials() or {}
        return creds.get("google_email", ""), creds.get("google_password", "")


# Module-level singleton
_identity_manager: Optional[IdentityManager] = None


def get_identity_manager() -> IdentityManager:
    global _identity_manager
    if _identity_manager is None:
        _identity_manager = IdentityManager()
    return _identity_manager
