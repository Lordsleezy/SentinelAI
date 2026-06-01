"""HackerOne / bounty-targets-data scanner.

Data schema (as of current arkadiyt/bounty-targets-data):
  - handle, name, id, url, website
  - offers_bounties (bool)
  - submission_state: 'open' | 'closed'
  - managed_program (bool)
  - average_time_to_bounty_awarded (float, days)
  - targets: {in_scope: [{asset_identifier, asset_type, eligible_for_bounty,
                           max_severity, ...}], out_of_scope: [...]}

Note: explicit dollar bounty amounts are NOT in this dataset. We derive
reward display from max_severity of in-scope assets.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SOURCE_NAME = "bounty_targets"

_SEVERITY_REWARD_HINT = {
    "critical": "Up to $10k+",
    "high":     "Up to $2,500",
    "medium":   "Up to $500",
    "low":      "Up to $100",
}


def parse_hackerone_program(program: Dict[str, Any]) -> Dict[str, Any]:
    offers_bounties = program.get("offers_bounties", False)

    # Extract in-scope targets from the actual data structure
    targets = program.get("targets") or {}
    in_scope_raw = targets.get("in_scope") or []

    eligible_scopes = [s for s in in_scope_raw if s.get("eligible_for_bounty")]
    scope_identifiers = [s.get("asset_identifier", "") for s in eligible_scopes if s.get("asset_identifier")]

    # Derive reward hint from highest severity found
    severities = [s.get("max_severity", "").lower() for s in eligible_scopes if s.get("max_severity")]
    _order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    best_severity = min(severities, key=lambda s: _order.get(s, 99), default=None) if severities else None

    if offers_bounties:
        if best_severity and best_severity in _SEVERITY_REWARD_HINT:
            reward = _SEVERITY_REWARD_HINT[best_severity]
        else:
            reward = "Varies"
    else:
        reward = "VDP"

    avg_days = program.get("average_time_to_bounty_awarded")
    handle = program.get("handle") or program.get("name", "unknown")

    return {
        "source": "hackerone",
        "title": program.get("name") or handle,
        "program": handle,
        "reward": reward,
        "reward_range": reward,
        "max_severity": best_severity or "varies",
        "offers_bounties": offers_bounties,
        "scope": scope_identifiers[:3],
        "scope_count": len(scope_identifiers),
        "avg_days_to_bounty": round(avg_days, 0) if avg_days else None,
        "url": program.get("url") or f"https://hackerone.com/{handle}",
        "fetched_at": datetime.now().isoformat(),
        "type": "bounty",
    }


def scan(limit: int = 25) -> List[Dict[str, Any]]:
    """Return normalized bounty program dicts from bounty-targets-data.

    Bounty programs (offers_bounties=True) are returned first, sorted by
    highest severity available in their in-scope targets.
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

        # Sort: open bounty programs first, then by severity
        _sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "varies": 4}
        parsed.sort(key=lambda p: (
            0 if p["offers_bounties"] else 1,
            _sev_order.get(p.get("max_severity", "varies"), 5)
        ))

        bounty_programs = [p for p in parsed if p["offers_bounties"]]
        return bounty_programs[:limit] if bounty_programs else parsed[:limit]
    except Exception as exc:
        logger.debug("bounty_targets scan failed: %s", exc)
        return []
