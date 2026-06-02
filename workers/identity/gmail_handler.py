"""
workers/identity/gmail_handler.py
Reads Gmail inbox to find 2FA codes via Gmail API (OAuth).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
TOKEN_PATH = Path.home() / ".sentinelai" / "gmail_token.json"
CREDENTIALS_PATH = Path.home() / ".sentinelai" / "gmail_credentials.json"

SERVICE_SENDER_MAP = {
    "claude": ["anthropic.com", "no-reply@anthropic.com"],
    "chatgpt": ["openai.com", "no-reply@openai.com", "verify@openai.com"],
    "google": ["accounts.google.com", "no-reply@accounts.google.com"],
}


class GmailHandler:
    """
    Reads Gmail inbox to find 2FA codes.
    Uses Gmail API with OAuth (not password scraping).
    OAuth token saved to ~/.sentinelai/gmail_token.json
    """

    def __init__(self):
        self._service = None

    def authenticate(self) -> bool:
        """
        Run OAuth flow if no token exists.
        Opens browser for one-time Google authorization.
        Saves token for future use.
        Returns True if authenticated.
        """
        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build

            creds = None
            if TOKEN_PATH.exists():
                creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    if not CREDENTIALS_PATH.exists():
                        logger.warning(
                            "Gmail credentials.json not found at %s. "
                            "Download from Google Cloud Console.", CREDENTIALS_PATH
                        )
                        return False
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(CREDENTIALS_PATH), SCOPES
                    )
                    creds = flow.run_local_server(port=0)

                TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
                TOKEN_PATH.write_text(creds.to_json())

            self._service = build("gmail", "v1", credentials=creds)
            logger.info("[GmailHandler] Authenticated OK")
            return True

        except ImportError:
            logger.warning("[GmailHandler] google-api-python-client not installed")
            return False
        except Exception as e:
            logger.error("[GmailHandler] Authentication failed: %s", e)
            return False

    def _ensure_service(self) -> bool:
        if self._service is not None:
            return True
        return self.authenticate()

    def find_2fa_code(self, service: str, since_minutes: int = 5) -> Optional[str]:
        """
        Search inbox for recent 2FA emails from service.
        Returns 6-8 digit code string or None.
        """
        if not self._ensure_service():
            return None

        try:
            senders = SERVICE_SENDER_MAP.get(service, [])
            sender_query = " OR ".join(f"from:{s}" for s in senders) if senders else ""
            query = f"({sender_query}) newer_than:{since_minutes}m"

            results = self._service.users().messages().list(
                userId="me", q=query, maxResults=5
            ).execute()

            messages = results.get("messages", [])
            for msg_meta in messages:
                msg = self._service.users().messages().get(
                    userId="me", id=msg_meta["id"], format="full"
                ).execute()
                body = self._extract_body(msg)
                code = self._extract_code(body)
                if code:
                    logger.info("[GmailHandler] Found 2FA code for %s", service)
                    return code

        except Exception as e:
            logger.error("[GmailHandler] find_2fa_code error: %s", e)

        return None

    def _extract_body(self, message: dict) -> str:
        """Extract plain text body from Gmail message."""
        try:
            payload = message.get("payload", {})
            parts = payload.get("parts", [])
            if not parts:
                data = payload.get("body", {}).get("data", "")
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")

            for part in parts:
                if part.get("mimeType") == "text/plain":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
        except Exception:
            pass
        return ""

    def _extract_code(self, text: str) -> Optional[str]:
        """Extract 6-8 digit verification code from text."""
        match = re.search(r"\b(\d{6,8})\b", text)
        return match.group(1) if match else None

    def is_configured(self) -> bool:
        """True if OAuth token exists and is usable."""
        return TOKEN_PATH.exists()
