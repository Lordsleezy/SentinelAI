"""
workers/identity/browser_sessions.py
Manages persistent logged-in browser sessions for Claude.ai and ChatGPT
via Playwright. Sessions persist using browser storage/cookies.
Re-authenticates automatically when sessions expire.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from workers.identity.identity_manager import IdentityManager

logger = logging.getLogger(__name__)

_SENTINEL_DIR = Path.home() / ".sentinelai"
_BROWSER_DATA = _SENTINEL_DIR / "browser_data"


class BrowserSessions:
    """
    Manages persistent logged-in sessions for Claude.ai and ChatGPT.
    Uses StealthBrowser to avoid bot detection.
    Sessions persist via browser storage so login survives restarts.
    """

    def __init__(self, identity_manager: "IdentityManager", socketio=None):
        self.identity = identity_manager
        self.socketio = socketio
        self.claude_logged_in = False
        self.chatgpt_logged_in = False
        self._context = None
        self._playwright = None

    def _log(self, msg: str, level: str = "info", source: str = "identity"):
        logger.info("[%s] %s", source, msg)
        if self.socketio:
            try:
                from datetime import datetime
                self.socketio.emit("log_event", {
                    "type": source, "level": level,
                    "message": msg, "timestamp": datetime.now().isoformat()
                })
            except Exception:
                pass

    # ── Public sync wrappers ───────────────────────────────────────────────────

    def startup_login(self):
        """Called on app startup in background thread. Logs into both services."""
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self._startup_login_async())
        except Exception as e:
            self._log(f"Browser session startup failed: {e}", "error")

    def login_claude(self) -> bool:
        try:
            loop = asyncio.new_event_loop()
            return loop.run_until_complete(self._login_claude_async())
        except Exception as e:
            self._log(f"Claude login error: {e}", "error")
            return False

    def login_chatgpt(self) -> bool:
        try:
            loop = asyncio.new_event_loop()
            return loop.run_until_complete(self._login_chatgpt_async())
        except Exception as e:
            self._log(f"ChatGPT login error: {e}", "error")
            return False

    def is_claude_logged_in(self) -> bool:
        return self.claude_logged_in

    def is_chatgpt_logged_in(self) -> bool:
        return self.chatgpt_logged_in

    def ensure_claude_session(self) -> bool:
        if self.claude_logged_in:
            return True
        return self.login_claude()

    def ensure_chatgpt_session(self) -> bool:
        if self.chatgpt_logged_in:
            return True
        return self.login_chatgpt()

    # ── Async implementation ───────────────────────────────────────────────────

    async def _get_context(self):
        """Return (or create) a persistent browser context with stealth settings."""
        if self._context is not None:
            return self._context
        try:
            from playwright.async_api import async_playwright
            from workers.identity.stealth_browser import StealthBrowser
            stealth = StealthBrowser()
            pw = await async_playwright().start()
            self._playwright = pw
            self._context = await stealth.launch_context(pw)
            self._stealth = stealth
            return self._context
        except ImportError:
            self._log("playwright not installed — browser sessions disabled", "warning")
            raise
        except Exception as e:
            self._log(f"Browser context creation failed: {e}", "error")
            raise

    async def _startup_login_async(self):
        self._log("Browser session startup beginning...", "info")
        creds = self.identity.load_credentials() or {}

        has_claude = bool(creds.get("claude_email")) and bool(creds.get("claude_password"))
        has_chatgpt = bool(creds.get("chatgpt_email")) and bool(creds.get("chatgpt_password"))

        if not has_claude and not has_chatgpt:
            self._log("No credentials configured — skipping browser login", "info")
            return

        if has_claude:
            self._log("Logging into Claude.ai...", "info")
            self.claude_logged_in = await self._login_claude_async()
            status = "connected" if self.claude_logged_in else "failed"
            self._log(f"Claude.ai: {status}", "info" if self.claude_logged_in else "warning")

        if has_chatgpt:
            await asyncio.sleep(random.uniform(1.5, 3.0))
            self._log("Logging into ChatGPT...", "info")
            self.chatgpt_logged_in = await self._login_chatgpt_async()
            status = "connected" if self.chatgpt_logged_in else "failed"
            self._log(f"ChatGPT: {status}", "info" if self.chatgpt_logged_in else "warning")

    async def _login_claude_async(self) -> bool:
        creds = self.identity.load_credentials() or {}
        email = creds.get("claude_email", "")
        password = creds.get("claude_password", "")
        if not email or not password:
            return False
        try:
            ctx = await self._get_context()
            stealth = self._stealth
            page = await stealth.new_page(ctx)
            await page.goto("https://claude.ai", wait_until="domcontentloaded")
            await asyncio.sleep(random.uniform(1.5, 2.5))

            # Check if already logged in
            if await self._is_logged_in(page, "claude"):
                self._log("Claude.ai: already logged in", "success")
                await page.close()
                return True

            # Click login button
            await self._click_if_exists(page, 'a[href*="login"], button:has-text("Log in"), a:has-text("Log in")')
            await asyncio.sleep(random.uniform(0.8, 1.5))

            # Enter email
            await stealth.human_type(page, 'input[type="email"], input[name="email"]', email)
            await stealth.human_click(page, 'button[type="submit"], button:has-text("Continue")')
            await asyncio.sleep(random.uniform(1.0, 2.0))

            # Enter password
            await stealth.human_type(page, 'input[type="password"]', password)
            await stealth.human_click(page, 'button[type="submit"]')
            await asyncio.sleep(random.uniform(2.0, 3.5))

            # Handle 2FA if needed
            success = await self._handle_post_login(page, "claude")
            await page.close()
            return success
        except Exception as e:
            self._log(f"Claude login failed: {e}", "error")
            return False

    async def _login_chatgpt_async(self) -> bool:
        creds = self.identity.load_credentials() or {}
        email = creds.get("chatgpt_email", "")
        password = creds.get("chatgpt_password", "")
        if not email or not password:
            return False
        try:
            ctx = await self._get_context()
            stealth = self._stealth
            page = await stealth.new_page(ctx)
            await page.goto("https://chatgpt.com", wait_until="domcontentloaded")
            await asyncio.sleep(random.uniform(1.5, 2.5))

            if await self._is_logged_in(page, "chatgpt"):
                self._log("ChatGPT: already logged in", "success")
                await page.close()
                return True

            # Click login
            await self._click_if_exists(page, 'button:has-text("Log in"), a:has-text("Log in")')
            await asyncio.sleep(random.uniform(0.8, 1.5))

            await stealth.human_type(page, 'input[name="username"], input[type="email"]', email)
            await stealth.human_click(page, 'button[type="submit"], button[data-action-button-primary]')
            await asyncio.sleep(random.uniform(1.0, 2.0))

            await stealth.human_type(page, 'input[type="password"]', password)
            await stealth.human_click(page, 'button[type="submit"]')
            await asyncio.sleep(random.uniform(2.0, 3.5))

            success = await self._handle_post_login(page, "chatgpt")
            await page.close()
            return success
        except Exception as e:
            self._log(f"ChatGPT login failed: {e}", "error")
            return False

    async def _handle_post_login(self, page, service: str) -> bool:
        """After password submission: handle 2FA or verify success."""
        await asyncio.sleep(2)
        two_fa_selectors = [
            'input[autocomplete="one-time-code"]',
            'input[placeholder*="code" i]',
            'input[placeholder*="verification" i]',
            '[data-testid*="2fa"]',
            '[data-testid*="otp"]',
        ]
        for sel in two_fa_selectors:
            el = await page.query_selector(sel)
            if el:
                self._log(f"2FA prompt detected for {service}", "info")
                try:
                    from workers.identity.two_factor import TwoFactorHandler
                    handler = TwoFactorHandler(self.identity)
                    await handler.handle_2fa_prompt_async(page, service, self._stealth)
                except Exception as e:
                    self._log(f"2FA handling failed: {e}", "error")
                    return False
                await asyncio.sleep(2)
                break

        result = await self._is_logged_in(page, service)
        if result:
            self._log(f"{service}: login successful", "success")
        else:
            self._log(f"{service}: login may have failed — check credentials", "warning")
        return result

    async def _is_logged_in(self, page, service: str) -> bool:
        """Quick check — is the session valid?"""
        try:
            # Look for common logged-in indicators
            logged_in_selectors = {
                "claude": ['[data-testid="user-menu"], .user-avatar, [aria-label*="account" i]'],
                "chatgpt": ['[data-testid="profile-button"], .avatar, nav [href="/"] + *'],
            }
            for sel in logged_in_selectors.get(service, []):
                el = await page.query_selector(sel)
                if el:
                    return True
            # URL-based check
            url = page.url
            if service == "claude" and "claude.ai" in url and "/login" not in url:
                return True
            if service == "chatgpt" and "chatgpt.com" in url and "auth" not in url:
                return True
        except Exception:
            pass
        return False

    async def _click_if_exists(self, page, selector: str):
        try:
            el = await page.query_selector(selector)
            if el:
                await el.click()
        except Exception:
            pass
