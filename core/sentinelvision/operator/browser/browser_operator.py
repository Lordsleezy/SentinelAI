"""Browser operator — Playwright-backed when available."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("sentinel.vision.browser")

_SCREENSHOT_DIR = Path(__file__).resolve().parents[4] / "data" / "sentinelvision" / "screenshots"


class BrowserOperator:
    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._page = None
        self._backend = self._detect_backend()

    def _detect_backend(self) -> str:
        try:
            import playwright  # noqa: F401
            return "playwright"
        except ImportError:
            return "unavailable"

    @property
    def available(self) -> bool:
        return self._backend == "playwright"

    def _ensure_page(self):
        if self._backend != "playwright":
            raise RuntimeError(
                "Playwright not installed. Run: pip install playwright && playwright install chromium"
            )
        if self._page is None:
            from playwright.sync_api import sync_playwright
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)
            self._page = self._browser.new_page()

    def close(self) -> None:
        try:
            if self._page:
                self._page.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        self._page = self._browser = self._playwright = None

    def open_url(self, url: str) -> Dict[str, Any]:
        self._ensure_page()
        self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
        return {"ok": True, "url": self._page.url, "title": self._page.title()}

    def click(self, selector: str) -> Dict[str, Any]:
        self._ensure_page()
        self._page.click(selector, timeout=30000)
        return {"ok": True, "selector": selector}

    def type(self, selector: str, text: str, *, clear: bool = True) -> Dict[str, Any]:
        self._ensure_page()
        if clear:
            self._page.fill(selector, text, timeout=30000)
        else:
            self._page.type(selector, text, timeout=30000)
        return {"ok": True, "selector": selector, "length": len(text)}

    def select(self, selector: str, value: str) -> Dict[str, Any]:
        self._ensure_page()
        self._page.select_option(selector, value)
        return {"ok": True}

    def upload_file(self, selector: str, path: str) -> Dict[str, Any]:
        self._ensure_page()
        self._page.set_input_files(selector, path)
        return {"ok": True, "path": path}

    def download_file(self, url: str, dest: str) -> Dict[str, Any]:
        import httpx
        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
            dest_path.write_bytes(r.content)
        return {"ok": True, "path": str(dest_path), "bytes": dest_path.stat().st_size}

    def wait_for_element(self, selector: str, timeout_ms: int = 30000) -> Dict[str, Any]:
        self._ensure_page()
        self._page.wait_for_selector(selector, timeout=timeout_ms)
        return {"ok": True, "selector": selector}

    def extract_text(self, selector: Optional[str] = None) -> Dict[str, Any]:
        self._ensure_page()
        if selector:
            text = self._page.inner_text(selector)
        else:
            text = self._page.inner_text("body")
        return {"ok": True, "text": (text or "")[:10000]}

    def capture_screenshot(self, name: str = "screen") -> Dict[str, Any]:
        self._ensure_page()
        _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = _SCREENSHOT_DIR / f"{name}.png"
        self._page.screenshot(path=str(path), full_page=False)
        return {"ok": True, "path": str(path)}

    def click_by_text(self, text: str, *, exact: bool = False) -> Dict[str, Any]:
        """Playwright get_by_text locator."""
        self._ensure_page()
        loc = self._page.get_by_text(text, exact=exact)
        loc.first.click(timeout=30000)
        return {"ok": True, "method": "text", "text": text}

    def smart_click(
        self,
        *,
        selector: Optional[str] = None,
        text: Optional[str] = None,
        vision_target: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fallback order: selector → text → OCR → vision model."""
        if selector:
            try:
                return self.click(selector)
            except Exception as e:
                last_err = str(e)
        else:
            last_err = ""

        if text:
            try:
                return self.click_by_text(text)
            except Exception as e:
                last_err = str(e)

        ocr_target = vision_target or text
        if ocr_target:
            from core.sentinelvision.operator.browser.ocr_bridge import (
                find_text_on_screen,
                ocr_available,
                suggest_click_labels_from_ocr,
            )
            if ocr_available():
                try:
                    shot = self.capture_screenshot("smart_click_ocr")
                    ocr = find_text_on_screen(shot.get("path", ""), ocr_target)
                    if ocr.get("found"):
                        for label in suggest_click_labels_from_ocr(shot.get("path", ""), ocr_target):
                            try:
                                return self.click_by_text(label, exact=False)
                            except Exception:
                                continue
                except Exception as e:
                    last_err = str(e)

        if vision_target:
            from core.sentinelvision.operator.browser.vision_bridge import find_click_target, vision_available
            if not vision_available():
                return {"ok": False, "error": f"vision unavailable; prior errors: {last_err}"}
            shot = self.capture_screenshot("smart_click")
            vis = find_click_target(shot.get("path", ""), vision_target)
            if not vis.get("ok"):
                return {"ok": False, "error": vis.get("error", last_err)}
            labels = vis.get("suggested_labels") or []
            for label in labels:
                try:
                    return self.click_by_text(label.strip(), exact=False)
                except Exception:
                    continue
            for word in vision_target.split():
                if len(word) > 3:
                    try:
                        return self.click_by_text(word, exact=False)
                    except Exception:
                        continue
            return {
                "ok": False,
                "error": last_err or "vision could not locate click target",
                "vision_analysis": vis.get("analysis", "")[:500],
            }

        return {"ok": False, "error": last_err or "no selector, text, or vision_target"}

    def smart_fill(
        self,
        text: str,
        *,
        selector: Optional[str] = None,
        placeholder: Optional[str] = None,
    ) -> Dict[str, Any]:
        if selector:
            try:
                return self.type(selector, text)
            except Exception:
                pass
        if placeholder:
            try:
                self._ensure_page()
                self._page.get_by_placeholder(placeholder).fill(text, timeout=30000)
                return {"ok": True, "method": "placeholder", "placeholder": placeholder}
            except Exception:
                pass
        return {"ok": False, "error": "smart_fill failed"}

    def browser_state(self) -> Dict[str, Any]:
        if not self._page:
            return {"ok": False, "open": False}
        try:
            return {
                "ok": True,
                "open": True,
                "url": self._page.url,
                "title": self._page.title(),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
