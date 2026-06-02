"""
workers/identity/stealth_browser.py
Wraps Playwright with full bot-detection evasion.
Use this instead of raw Playwright for ALL browser automation.

What it hides:
- webdriver flag (biggest bot signal)
- Chrome automation flags
- Canvas fingerprint (randomized per session)
- WebGL fingerprint (spoofed)
- Navigator plugins (faked to look like real Chrome)
- Screen resolution (realistic values)
- Timezone (matches system)
- Language headers
- CDP detection
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from typing import Optional

logger = logging.getLogger(__name__)

REALISTIC_VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1280, "height": 720},
    {"width": 2560, "height": 1440},
]

STORAGE_PATH = os.path.expanduser("~/.sentinelai/browser_data")


def _get_stealth():
    """Lazy import stealth module with version compatibility."""
    try:
        from playwright_stealth import Stealth
        return Stealth()
    except ImportError:
        return None


class StealthBrowser:
    """
    Wraps Playwright with full bot-detection evasion.
    Use this instead of raw Playwright for ALL browser automation.
    """

    def __init__(self):
        self.viewport = random.choice(REALISTIC_VIEWPORTS)
        self.user_agent = self._get_random_ua()
        self._stealth = _get_stealth()

    def _get_random_ua(self) -> str:
        try:
            from fake_useragent import UserAgent
            ua = UserAgent(browsers=["chrome"], os=["windows"])
            return ua.random
        except Exception:
            return (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            )

    async def launch_context(self, playwright):
        """
        Launch a persistent browser context with stealth settings.
        Uses persistent storage so sessions/cookies survive restarts.
        Storage path: ~/.sentinelai/browser_data/
        """
        os.makedirs(STORAGE_PATH, exist_ok=True)
        context = await playwright.chromium.launch_persistent_context(
            STORAGE_PATH,
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-dev-shm-usage",
                "--disable-extensions",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-default-apps",
                "--disable-popup-blocking",
            ],
            user_agent=self.user_agent,
            viewport=self.viewport,
            locale="en-US",
            timezone_id="America/Los_Angeles",
            ignore_https_errors=True,
        )
        return context

    async def new_page(self, browser_context):
        """
        Create a new stealth page.
        Applies all evasion patches.
        Returns a Playwright page that looks like a real browser.
        """
        page = await browser_context.new_page()

        # Apply stealth patches
        if self._stealth is not None:
            try:
                await self._stealth.apply_stealth_async(page)
            except Exception as e:
                logger.debug("Stealth apply failed: %s", e)
        else:
            # Fallback: manual webdriver flag removal
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined,
                });
                window.chrome = { runtime: {} };
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5],
                });
            """)

        await page.set_viewport_size(self.viewport)
        await page.set_extra_http_headers({
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        return page

    async def human_type(self, page, selector: str, text: str):
        """Type text with human-like random delays between keystrokes."""
        await page.click(selector)
        await asyncio.sleep(random.uniform(0.3, 0.7))
        for char in text:
            await page.keyboard.type(char)
            await asyncio.sleep(random.uniform(0.05, 0.18))

    async def human_click(self, page, selector: str):
        """Click with a small random offset and human-like delay."""
        element = await page.query_selector(selector)
        if element:
            box = await element.bounding_box()
            if box:
                x = box["x"] + box["width"] / 2 + random.uniform(-3, 3)
                y = box["y"] + box["height"] / 2 + random.uniform(-2, 2)
                await asyncio.sleep(random.uniform(0.1, 0.4))
                await page.mouse.move(x, y)
                await asyncio.sleep(random.uniform(0.05, 0.15))
                await page.mouse.click(x, y)

    async def random_scroll(self, page):
        """Scroll randomly like a human reading the page."""
        for _ in range(random.randint(1, 3)):
            await page.mouse.wheel(0, random.randint(100, 400))
            await asyncio.sleep(random.uniform(0.3, 0.8))

    def rotate_user_agent(self) -> str:
        """Get a fresh random user agent for next session."""
        self.user_agent = self._get_random_ua()
        return self.user_agent

    def verify_stealth(self) -> bool:
        """Return True if stealth library is loaded and ready."""
        return self._stealth is not None
