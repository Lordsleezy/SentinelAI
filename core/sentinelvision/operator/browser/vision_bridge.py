"""Sentinel Vision bridge — Ollama llava / vision models for browser UI."""
from __future__ import annotations

import base64
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sentinel.vision.vision")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
VISION_MODEL = os.getenv("SENTINEL_VISION_MODEL", "llava")


def vision_available() -> bool:
    try:
        import httpx
        r = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=3.0)
        if r.status_code != 200:
            return False
        models = [m.get("name", "") for m in r.json().get("models", [])]
        return any(VISION_MODEL.split(":")[0] in n for n in models)
    except Exception:
        return False


def analyze_screenshot(
    image_path: str,
    prompt: str,
    *,
    timeout: float = 45.0,
) -> Dict[str, Any]:
    path = Path(image_path)
    if not path.is_file():
        return {"ok": False, "error": f"screenshot not found: {image_path}"}
    try:
        import httpx
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        with httpx.Client(timeout=timeout) as client:
            r = client.post(
                f"{OLLAMA_HOST}/api/generate",
                json={
                    "model": VISION_MODEL,
                    "prompt": prompt,
                    "images": [b64],
                    "stream": False,
                },
            )
        if r.status_code != 200:
            return {"ok": False, "error": f"vision API {r.status_code}"}
        text = (r.json().get("response") or "").strip()
        return {"ok": True, "analysis": text, "model": VISION_MODEL}
    except Exception as e:
        logger.warning("vision analyze failed: %s", e)
        return {"ok": False, "error": str(e)}


def find_click_target(
    image_path: str,
    target_description: str,
) -> Dict[str, Any]:
    prompt = (
        f"You are assisting browser automation. The user wants to interact with: {target_description}.\n"
        "Describe precisely what you see: login forms, buttons (with visible labels), error dialogs, "
        "confirmation screens. If you can estimate button position, say 'CLICK: label' for the best match."
    )
    result = analyze_screenshot(image_path, prompt)
    if not result.get("ok"):
        return result
    analysis = result.get("analysis", "")
    labels = re.findall(r"CLICK:\s*([^\n]+)", analysis, re.I)
    return {
        "ok": True,
        "analysis": analysis,
        "suggested_labels": labels,
        "has_login_form": "login" in analysis.lower() or "password" in analysis.lower(),
        "has_error_dialog": "error" in analysis.lower() or "failed" in analysis.lower(),
    }


def identify_page_elements(image_path: str) -> Dict[str, Any]:
    return analyze_screenshot(
        image_path,
        "List interactive UI elements: buttons, links, input fields, error messages. "
        "One per line as: TYPE | LABEL",
    )
