"""HackerOne / Bugcrowd / bounty-targets-data scanner."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SOURCE_NAME = "bounty_targets"


def parse_hackerone_program(program: Dict[str, Any]) -> Dict[str, Any]:
    bounty_min = program.get("minimum_bounty_table_value") or 0
    bounty_max = program.get("maximum_bounty_table_value") or 0
    offers_bounties = program.get("offers_bounties", False)

    if bounty_max and bounty_max > 0:
        reward = f"${int(bounty_min):,} - ${int(bounty_max):,}"
    elif offers_bounties:
        reward = "Bounty offered"
    else:
        reward = "VDP (no bounty)"

    scopes = program.get("structured_scopes") or []
    in_scope = [s.get("asset_identifier", "") for s in scopes if s.get("eligible_for_bounty")]

    handle = program.get("handle") or program.get("name", "unknown")
    return {
        "source": "hackerone",
        "title": program.get("name") or handle,
        "program": handle,
        "reward": reward,
        "reward_range": reward,
        "offers_bounties": offers_bounties,
        "scope": in_scope[:3],
        "url": f"https://hackerone.com/{handle}",
        "fetched_at": datetime.now().isoformat(),
        "type": "bounty",
    }


def scan(limit: int = 25) -> List[Dict[str, Any]]:
    """Return normalized bounty program dicts from bounty-targets-data.

    Bounty programs (offers_bounties=True) are returned first.
    """
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

        parsed = [parse_hackerone_program(item) for item in raw if isinstance(item, dict)]

        # Sort: bounty programs first, then VDP
        parsed.sort(key=lambda p: (0 if p["offers_bounties"] else 1))

        # Default view: bounty programs only (up to limit)
        bounty_programs = [p for p in parsed if p["offers_bounties"]]
        return bounty_programs[:limit] if bounty_programs else parsed[:limit]
    except Exception as exc:
        logger.debug("bounty_targets scan failed: %s", exc)
        return []
