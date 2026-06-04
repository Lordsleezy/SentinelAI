"""Capture failure context — logs, screenshots, terminal, browser state."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger("sentinel.vision.capture")


@dataclass
class FailureBundle:
    error: str
    logs: list = field(default_factory=list)
    screenshot_path: Optional[str] = None
    terminal_stdout: str = ""
    terminal_stderr: str = ""
    browser_url: Optional[str] = None
    browser_title: Optional[str] = None
    browser_text_excerpt: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_context(self) -> Dict[str, Any]:
        return {
            "error": self.error,
            "logs": self.logs[-50:],
            "screenshot_path": self.screenshot_path,
            "terminal_stdout": self.terminal_stdout,
            "terminal_stderr": self.terminal_stderr,
            "browser_url": self.browser_url,
            "browser_title": self.browser_title,
            "browser_text_excerpt": self.browser_text_excerpt,
            **self.extra,
        }


def capture_failure_context(
    error: str,
    *,
    browser=None,
    desktop=None,
    last_terminal: Optional[Dict[str, Any]] = None,
    goal_id: Optional[str] = None,
) -> FailureBundle:
    bundle = FailureBundle(error=str(error))

    if last_terminal:
        bundle.terminal_stdout = (last_terminal.get("stdout") or "")[-8000:]
        bundle.terminal_stderr = (last_terminal.get("stderr") or "")[-4000:]

    if browser and getattr(browser, "available", False):
        try:
            shot = browser.capture_screenshot(name=f"failure_{goal_id or 'x'}")
            bundle.screenshot_path = shot.get("path")
            text = browser.extract_text()
            bundle.browser_text_excerpt = (text.get("text") or "")[:3000]
            if browser._page:
                bundle.browser_url = browser._page.url
                bundle.browser_title = browser._page.title()
        except Exception as e:
            bundle.logs.append(f"screenshot capture failed: {e}")

    return bundle
