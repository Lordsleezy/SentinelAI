"""Upwork scanner (Pro tier).

Minimal scaffold. Requires UPWORK_API_TOKEN. Upwork's public listing API has
been deprecated; this scanner falls back to RSS feeds when available.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SOURCE_NAME = "upwork"


def scan(limit: int = 25) -> List[Dict[str, Any]]:
    token = os.getenv("UPWORK_API_TOKEN")
    if not token:
        logger.info("UPWORK_API_TOKEN not set — skipping scan")
        return []
    try:
        import feedparser  # type: ignore
    except Exception as exc:  # pragma: no cover
        logger.debug("feedparser unavailable: %s", exc)
        return []
    rss_url = os.getenv("UPWORK_RSS_URL")
    if not rss_url:
        return []
    try:
        feed = feedparser.parse(rss_url)
        entries = getattr(feed, "entries", []) or []
        return [
            {"title": e.get("title"), "link": e.get("link"),
             "summary": e.get("summary")} for e in entries[:limit]
        ]
    except Exception as exc:
        logger.debug("upwork scan failed: %s", exc)
        return []
