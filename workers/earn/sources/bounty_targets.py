"""HackerOne / Bugcrowd / bounty-targets-data scanner.

Minimal scaffold — the live scanner lives in the root-level scanner.py. This
module exists so the orchestration pipeline can import it as a uniform earn
source.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SOURCE_NAME = "bounty_targets"


def scan(limit: int = 25) -> List[Dict[str, Any]]:
    """Return a list of opportunities from bounty-targets-data.

    Returns [] when no credentials are available or on any network failure.
    """
    try:
        import httpx
    except Exception as exc:  # pragma: no cover
        logger.debug("httpx unavailable: %s", exc)
        return []
    url = ("https://raw.githubusercontent.com/arkadiyt/"
           "bounty-targets-data/main/data/hackerone_data.json")
    try:
        response = httpx.get(url, timeout=10)
        if response.status_code != 200:
            return []
        return response.json()[:limit]
    except Exception as exc:
        logger.debug("bounty_targets scan failed: %s", exc)
        return []
