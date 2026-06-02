"""
Enrich bounty program records for the Earn Discovery Dashboard.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from workers.earn.hackerone_intel import (
    _MOBILE_TYPES,
    _asset_from_raw,
    _classify_url_asset,
)

_PLATFORM_LABELS = {
    "hackerone": "HackerOne",
    "bugcrowd": "Bugcrowd",
    "intigriti": "Intigriti",
}

_SEV_BOUNTY_USD = {"critical": 10000, "high": 2500, "medium": 500, "low": 100}


def _parse_bounty_usd(reward: str, attrs: Optional[Dict] = None) -> Tuple[Optional[int], Optional[int]]:
    """Return (min_usd, max_usd) from display string or attrs tables."""
    attrs = attrs or {}
    min_b = attrs.get("minimum_bounty_table") or {}
    max_b = attrs.get("maximum_bounty_table") or {}
    try:
        vals = []
        for k in ("critical", "high", "medium", "low"):
            for tbl in (min_b, max_b):
                v = tbl.get(k)
                if v is not None:
                    vals.append(int(float(v)))
        if vals:
            return min(vals), max(vals)
    except (TypeError, ValueError):
        pass

    if not reward:
        return None, None
    nums = [int(x.replace(",", "")) for x in re.findall(r"\$?([\d,]+)", reward)]
    if not nums:
        return None, None
    return min(nums), max(nums)


def _summarize_targets(targets: Dict[str, Any]) -> Dict[str, Any]:
    in_raw = targets.get("in_scope") or []
    out_raw = targets.get("out_of_scope") or []
    assets = [_asset_from_raw(s) for s in in_raw if s.get("asset_identifier")]
    eligible = [a for a in assets if a.eligible_for_bounty]

    has_mobile = any(a.category == "mobile" for a in eligible)
    has_api = any(a.category == "api" for a in eligible)
    has_web = any(
        a.category in ("web_general", "commerce", "ads_partners", "authentication", "cms_admin", "messaging", "file_upload")
        or (a.asset_type == "URL" and a.category != "mobile" and a.category != "api")
        for a in eligible
    )
    if not has_web and eligible and not has_mobile and not has_api:
        has_web = True

    domains: List[str] = []
    for a in eligible:
        ident = a.identifier
        if "." in ident and not ident.startswith("SUPERAPP"):
            host = ident.split("/")[0].strip().lower()
            if host and host not in domains:
                domains.append(host)

    mobile_ids = [a.identifier for a in eligible if a.category == "mobile"]

    return {
        "asset_count": len(eligible),
        "out_scope_count": len(out_raw),
        "has_web": has_web,
        "has_mobile": has_mobile,
        "has_api": has_api,
        "domains": domains[:20],
        "mobile_targets": mobile_ids,
    }


def enrich_program(program: Dict[str, Any], raw_record: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Add dashboard fields to a normalized program dict."""
    raw = raw_record or program
    targets = program.get("targets") or raw.get("targets") or {}
    summary = _summarize_targets(targets)
    src = (program.get("source") or "hackerone").lower()
    platform = _PLATFORM_LABELS.get(src, src.title() or "Unknown")
    attrs = raw.get("attributes") if raw_record else program.get("attributes") or {}
    reward = program.get("reward") or program.get("max_bounty") or ""
    bmin, bmax = _parse_bounty_usd(reward, attrs if isinstance(attrs, dict) else None)
    if bmax is None and program.get("max_severity"):
        bmax = _SEV_BOUNTY_USD.get(str(program.get("max_severity")).lower())

    handle = program.get("handle") or program.get("program") or ""
    title = program.get("title") or program.get("name") or handle
    scope_full = program.get("scope_full") or program.get("scope") or []

    search_parts = [title, handle, platform, reward, program.get("website") or ""]
    search_parts.extend(scope_full)
    search_parts.extend(summary.get("domains") or [])
    search_blob = " ".join(search_parts).lower()

    state = (program.get("submission_state") or "open").lower()
    is_active = state == "open" and bool(program.get("offers_bounties", True))

    out = dict(program)
    out.update({
        "platform": platform,
        "asset_count": summary["asset_count"],
        "out_scope_count": summary["out_scope_count"],
        "has_web": summary["has_web"],
        "has_mobile": summary["has_mobile"],
        "has_api": summary["has_api"],
        "domains": summary["domains"],
        "mobile_targets": summary["mobile_targets"],
        "bounty_min_usd": bmin,
        "bounty_max_usd": bmax,
        "bounty_display": reward,
        "search_blob": search_blob,
        "last_updated": program.get("cached_at") or program.get("fetched_at") or "",
        "is_active": is_active,
        "description": program.get("website") or f"https://hackerone.com/{handle}",
    })
    return out


def compute_overview(programs: List[Dict[str, Any]]) -> Dict[str, Any]:
    active = [p for p in programs if p.get("is_active")]
    web_n = sum(1 for p in programs if p.get("has_web"))
    mob_n = sum(1 for p in programs if p.get("has_mobile"))
    api_n = sum(1 for p in programs if p.get("has_api"))
    maxes = [p.get("bounty_max_usd") for p in programs if p.get("bounty_max_usd")]
    avgs = [p.get("bounty_max_usd") for p in active if p.get("bounty_max_usd")]

    highest = max(maxes) if maxes else None
    avg = round(sum(avgs) / len(avgs)) if avgs else None

    return {
        "programs_available": len(programs),
        "active_programs": len(active),
        "web_targets": web_n,
        "mobile_targets": mob_n,
        "api_targets": api_n,
        "highest_bounty_usd": highest,
        "highest_bounty_display": f"${highest:,}" if highest else "—",
        "average_bounty_usd": avg,
        "average_bounty_display": f"${avg:,}" if avg else "—",
    }
