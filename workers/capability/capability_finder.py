"""
Capability Finder — searches PyPI/GitHub for tools that fill a capability gap.

Minimal implementation. Network calls are guarded so an offline install never
raises an unhandled exception.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def search_pypi(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Search PyPI for packages matching ``query``. Returns [] on any failure."""
    try:
        import httpx  # local import keeps module import-light
    except Exception as exc:  # pragma: no cover
        logger.debug("httpx unavailable for PyPI search: %s", exc)
        return []
    url = f"https://pypi.org/search/?q={query}&format=json"
    try:
        response = httpx.get(url, timeout=5)
        if response.status_code != 200:
            return []
        payload = response.json()
        results = payload.get("results") or payload.get("info") or []
        return list(results)[:limit] if isinstance(results, list) else []
    except Exception as exc:
        logger.debug("PyPI search failed: %s", exc)
        return []


def search_github(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Search GitHub for repos matching ``query``. Returns [] on any failure."""
    try:
        import httpx
    except Exception as exc:  # pragma: no cover
        logger.debug("httpx unavailable for GitHub search: %s", exc)
        return []
    url = f"https://api.github.com/search/repositories?q={query}&per_page={limit}"
    try:
        response = httpx.get(url, timeout=5)
        if response.status_code != 200:
            return []
        return response.json().get("items", [])
    except Exception as exc:
        logger.debug("GitHub search failed: %s", exc)
        return []
