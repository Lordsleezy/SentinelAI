"""OCR fallback for browser interaction (step 3 in vision priority)."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sentinel.vision.ocr")


def ocr_available() -> bool:
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
        return True
    except ImportError:
        return False


def extract_text_from_image(image_path: str) -> Dict[str, Any]:
    if not ocr_available():
        return {"ok": False, "error": "pytesseract and Pillow required: pip install pytesseract pillow"}
    try:
        from PIL import Image
        import pytesseract
        text = pytesseract.image_to_string(Image.open(image_path))
        return {"ok": True, "text": (text or "").strip()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def find_text_on_screen(image_path: str, target: str) -> Dict[str, Any]:
    result = extract_text_from_image(image_path)
    if not result.get("ok"):
        return result
    text = result.get("text", "")
    lower = text.lower()
    target_lower = target.lower()
    if target_lower in lower:
        return {"ok": True, "found": True, "match": target, "text_excerpt": text[:2000]}
    words = [w for w in target_lower.split() if len(w) > 3]
    partial = [w for w in words if w in lower]
    return {
        "ok": True,
        "found": len(partial) >= max(1, len(words) // 2),
        "partial_matches": partial,
        "text_excerpt": text[:2000],
    }


def suggest_click_labels_from_ocr(image_path: str, target: str) -> List[str]:
    result = extract_text_from_image(image_path)
    if not result.get("ok"):
        return []
    lines = [ln.strip() for ln in result.get("text", "").splitlines() if ln.strip()]
    target_words = set(target.lower().split())
    labels = []
    for ln in lines:
        if any(w in ln.lower() for w in target_words if len(w) > 2):
            labels.append(ln[:80])
    return labels[:8]
