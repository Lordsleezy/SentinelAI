"""
workers/identity/two_factor.py
Handles all common 2FA methods automatically.

Methods supported:
- TOTP (authenticator app) — primary, works offline
- Gmail 2FA email codes — via Gmail API
- SMS 2FA — via Android ADB bridge
- None — skip 2FA
"""
from __future__ import annotations

import logging
import time
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from workers.identity.identity_manager import IdentityManager
    from workers.identity.stealth_browser import StealthBrowser
    from workers.identity.gmail_handler import GmailHandler
    from workers.identity.adb_handler import ADBHandler

logger = logging.getLogger(__name__)


class TwoFactorHandler:
    """
    Handles all 2FA methods automatically.
    Called by BrowserSessions when a 2FA prompt is detected.
    """

    def __init__(self, identity_manager: "IdentityManager",
                 gmail_handler: Optional["GmailHandler"] = None,
                 adb_handler: Optional["ADBHandler"] = None):
        self.identity = identity_manager
        self.gmail = gmail_handler
        self.adb = adb_handler

    def _log(self, msg: str, level: str = "info"):
        logger.info("[2fa] %s", msg)

    def get_totp_code(self, service: str) -> Optional[str]:
        """
        Generate current TOTP code for service.
        service: "claude" | "chatgpt" | "google"
        Returns 6-digit code string or None if not configured.
        Waits for next code if current one is about to expire (<5 seconds remaining).
        """
        try:
            import pyotp
            creds = self.identity.load_credentials() or {}
            secret = creds.get(f"{service}_totp_secret", "")
            if not secret:
                return None

            totp = pyotp.TOTP(secret)

            # If current code expires in < 5 seconds, wait for next one
            time_remaining = 30 - (int(time.time()) % 30)
            if time_remaining < 5:
                self._log(f"TOTP for {service}: waiting {time_remaining}s for next code")
                time.sleep(time_remaining + 1)

            code = totp.now()
            self._log(f"TOTP code generated for {service} (expires in {30 - (int(time.time()) % 30)}s)")
            return code
        except ImportError:
            self._log("pyotp not installed", "warning")
            return None
        except Exception as e:
            self._log(f"TOTP generation failed for {service}: {e}", "error")
            return None

    def get_email_code(self, service: str, timeout: int = 60) -> Optional[str]:
        """
        Wait for a 2FA code to arrive via email.
        Polls Gmail inbox every 5 seconds for up to timeout seconds.
        """
        if not self.gmail:
            self._log("Gmail handler not configured for email 2FA", "warning")
            return None

        self._log(f"Waiting for email 2FA code for {service} (timeout={timeout}s)")
        start = time.time()
        while time.time() - start < timeout:
            try:
                code = self.gmail.find_2fa_code(service)
                if code:
                    self._log(f"Email 2FA code received for {service}")
                    return code
            except Exception as e:
                self._log(f"Gmail poll error: {e}", "warning")
            time.sleep(5)

        self._log(f"Email 2FA timeout for {service}", "error")
        return None

    def get_sms_code(self, timeout: int = 60) -> Optional[str]:
        """
        Read 2FA code from SMS via ADB.
        Polls for new SMS every 5 seconds up to timeout.
        """
        if not self.adb:
            self._log("ADB handler not configured for SMS 2FA", "warning")
            return None

        self._log(f"Waiting for SMS 2FA code (timeout={timeout}s)")
        return self.adb.wait_for_sms_code(timeout)

    def handle_2fa_prompt(self, page_sync, service: str) -> bool:
        """Sync version — for use outside async context."""
        import asyncio
        try:
            loop = asyncio.new_event_loop()
            return loop.run_until_complete(
                self.handle_2fa_prompt_async(page_sync, service, None)
            )
        except Exception as e:
            self._log(f"2FA sync handler failed: {e}", "error")
            return False

    async def handle_2fa_prompt_async(self, page, service: str,
                                       stealth: Optional["StealthBrowser"]) -> bool:
        """
        Detect and handle 2FA prompt on a Playwright page.
        Tries TOTP → email → SMS in priority order.
        Returns True if 2FA was handled successfully.
        """
        creds = self.identity.load_credentials() or {}
        method = creds.get(f"{service}_2fa_method", "none")

        if method == "none":
            return True  # No 2FA configured — consider it handled

        code: Optional[str] = None

        if method == "totp":
            code = self.get_totp_code(service)
        elif method == "email":
            code = self.get_email_code(service)
        elif method == "sms":
            code = self.get_sms_code()

        if not code:
            self._log(f"2FA required for {service} but no code available (method={method})", "error")
            return False

        self._log(f"Entering 2FA code for {service} (method={method})", "info")

        # Find and fill the 2FA input
        two_fa_selectors = [
            'input[autocomplete="one-time-code"]',
            'input[placeholder*="code" i]',
            'input[placeholder*="verification" i]',
            'input[placeholder*="6-digit" i]',
            '[data-testid*="2fa"] input',
            '[data-testid*="otp"] input',
        ]

        for selector in two_fa_selectors:
            try:
                el = await page.query_selector(selector)
                if el:
                    if stealth:
                        await stealth.human_type(page, selector, code)
                    else:
                        await page.fill(selector, code)

                    # Submit
                    await page.keyboard.press("Enter")
                    import asyncio as _asyncio
                    await _asyncio.sleep(2)
                    self._log(f"2FA code submitted for {service}", "success")
                    return True
            except Exception as e:
                logger.debug("2FA selector %s failed: %s", selector, e)

        self._log(f"Could not find 2FA input field for {service}", "error")
        return False

    def get_2fa_status(self) -> dict:
        """Return 2FA configuration status for all services."""
        creds = self.identity.load_credentials() or {}
        return {
            "claude_2fa_method": creds.get("claude_2fa_method", "none"),
            "chatgpt_2fa_method": creds.get("chatgpt_2fa_method", "none"),
            "gmail_configured": self.gmail.is_configured() if self.gmail else False,
            "adb_available": self.adb.is_available() if self.adb else False,
        }
