"""HackerOne / Bugcrowd / bounty-targets-data scanner."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SOURCE_NAME = "bounty_targets"


def scan(limit: int = 25) -> List[Dict[str, Any]]:
    """Return normalized bounty program dicts from bounty-targets-data."""
    try:
        import httpx
    except Exception as exc:
        logger.debug("httpx unavailable: %s", exc)
        return []
    url = ("https://raw.githubusercontent.com/arkadiyt/"
           "bounty-targets-data/main/data/hackerone_data.json")
    try:
        response = httpx.get(url, timeout=15)
        if response.status_code != 200:
            logger.debug("bounty_targets HTTP %s", response.status_code)
            return []
        raw = response.json()
        if not isinstance(raw, list):
            return []
        jobs = []
        for item in raw[:limit]:
            if not isinstance(item, dict):
                continue
            handle = item.get("handle") or item.get("name", "unknown")
            name = item.get("name") or handle
            jobs.append({
                "title": name,
                "handle": handle,
                "url": f"https://hackerone.com/{handle}",
                "offers_bounties": item.get("offers_bounties", False),
                "submission_state": item.get("submission_state", "open"),
                "type": "bounty",
                "source": "hackerone",
            })
        return jobs
    except Exception as exc:
        logger.debug("bounty_targets scan failed: %s", exc)
        return []
