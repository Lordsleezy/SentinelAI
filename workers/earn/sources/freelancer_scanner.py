"""Freelancer.com scanner (Pro tier).

Minimal scaffold. Requires FREELANCER_API_TOKEN.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SOURCE_NAME = "freelancer"


def scan(limit: int = 25) -> List[Dict[str, Any]]:
    token = os.getenv("FREELANCER_API_TOKEN")
    if not token:
        logger.info("FREELANCER_API_TOKEN not set — skipping scan")
        return []
    try:
        import httpx
    except Exception as exc:  # pragma: no cover
        logger.debug("httpx unavailable: %s", exc)
        return []
    url = "https://www.freelancer.com/api/projects/0.1/projects/active/"
    try:
        response = httpx.get(
            url,
            headers={"Freelancer-OAuth-V1": token},
            params={"limit": limit},
            timeout=10,
        )
        if response.status_code != 200:
            return []
        return response.json().get("result", {}).get("projects", [])
    except Exception as exc:
        logger.debug("freelancer scan failed: %s", exc)
        return []
