"""RemoteOK job scanner."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SOURCE_NAME = "remoteok"


def scan(limit: int = 25) -> List[Dict[str, Any]]:
    """Return normalized job dicts from remoteok.com/api."""
    try:
        import httpx
    except Exception as exc:
        logger.debug("httpx unavailable: %s", exc)
        return []
    try:
        response = httpx.get(
            "https://remoteok.com/api",
            headers={"User-Agent": "SentinelAI/1.0"},
            timeout=15,
        )
        if response.status_code != 200:
            logger.debug("remoteok HTTP %s", response.status_code)
            return []
        data = response.json()
        if not isinstance(data, list):
            return []
        raw_jobs = data[1:limit + 1]  # index 0 is API meta
        jobs = []
        for item in raw_jobs:
            if not isinstance(item, dict):
                continue
            jobs.append({
                "title": item.get("position") or "Remote Job",
                "company": item.get("company"),
                "url": item.get("url"),
                "tags": item.get("tags") or [],
                "salary": item.get("salary_min"),
                "type": "job",
                "source": "remoteok",
            })
        return jobs
    except Exception as exc:
        logger.debug("remoteok scan failed: %s", exc)
        return []
