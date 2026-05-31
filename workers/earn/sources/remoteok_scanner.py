"""RemoteOK job scanner.

Minimal scaffold. Pulls publicly listed jobs from remoteok.com/api.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SOURCE_NAME = "remoteok"


def scan(limit: int = 25) -> List[Dict[str, Any]]:
    try:
        import httpx
    except Exception as exc:  # pragma: no cover
        logger.debug("httpx unavailable: %s", exc)
        return []
    try:
        response = httpx.get(
            "https://remoteok.com/api",
            headers={"User-Agent": "SentinelAI/1.0"},
            timeout=10,
        )
        if response.status_code != 200:
            return []
        data = response.json()
        return data[1:limit + 1] if isinstance(data, list) else []
    except Exception as exc:
        logger.debug("remoteok scan failed: %s", exc)
        return []
