"""
Earn Discovery Dashboard — aggregate programs, overview, metrics, program details.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from workers.earn.dashboard_enrich import compute_overview, enrich_program
from workers.earn.earn_diagnostics import earn_log
from workers.earn.program_discovery import (
    _load_cache,
    _read_meta,
    discover_programs,
    get_discovery_diagnostics,
)

_VAULT = Path(__file__).resolve().parents[2] / "memory" / "vault"
_BOUNTIES = _VAULT / "bounties"
_METRICS_PATH = _VAULT / "earn_cache" / "dashboard_metrics.json"


def _count_analyzed_and_reports() -> Dict[str, int]:
    analyzed = 0
    reports = 0
    if not _BOUNTIES.is_dir():
        return {"programs_analyzed": 0, "reports_generated": 0}
    for p in _BOUNTIES.iterdir():
        if p.name.endswith("_intel.json"):
            analyzed += 1
        elif p.suffix == ".md" and not p.name.endswith("_intel.md"):
            reports += 1
    return {"programs_analyzed": analyzed, "reports_generated": reports}


def _estimate_reward_pool(programs: List[Dict[str, Any]]) -> int:
    total = 0
    for p in programs:
        if p.get("is_active") and p.get("bounty_max_usd"):
            total += int(p["bounty_max_usd"])
    return total


def load_metrics() -> Dict[str, Any]:
    base = _count_analyzed_and_reports()
    if _METRICS_PATH.is_file():
        try:
            base.update(json.loads(_METRICS_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    return base


def _discovery_meta_dict() -> Dict[str, Any]:
    diag = get_discovery_diagnostics()
    meta = _read_meta()
    return {
        "source": meta.get("source") or diag.get("program_source") or "unknown",
        "last_refresh": meta.get("last_refresh") or diag.get("last_refresh"),
        "cache_age_minutes": diag.get("cache_age_minutes"),
        "api_status": meta.get("api_status") or diag.get("api_status"),
        "duration_ms": meta.get("duration_ms") or diag.get("last_duration_ms"),
        "discovered_total": meta.get("discovered_total") or diag.get("discovered_total"),
        "upstream": diag.get("upstream"),
        "error": meta.get("error") or diag.get("last_error"),
    }


def fetch_dashboard_programs(
    refresh: bool = False,
    force: bool = False,
    socketio: Any = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    """Load all bounty programs for dashboard (from cache or upstream)."""
    if refresh or force:
        if force:
            earn_log(socketio, "Force refresh — bypassing cache")
        else:
            earn_log(socketio, "Discovery Started")
        programs, meta = discover_programs(
            limit=9999,
            force_refresh=force,
            refresh=refresh and not force,
            socketio=socketio,
        )
        disc = meta.to_dict()
    else:
        cached, _ = _load_cache()
        if not cached:
            programs, meta = discover_programs(limit=9999, socketio=socketio)
            disc = meta.to_dict()
        else:
            programs = cached
            disc = _discovery_meta_dict()

    enriched = [enrich_program(p) for p in programs if p.get("offers_bounties", True)]
    overview = compute_overview(enriched)
    overview.update(_discovery_meta_dict())
    overview["discovery_duration_s"] = round((disc.get("duration_ms") or 0) / 1000, 1)

    metrics = load_metrics()
    metrics["programs_discovered"] = disc.get("discovered_total") or len(enriched)
    metrics["potential_reward_pool_usd"] = _estimate_reward_pool(enriched)
    metrics["potential_reward_pool_display"] = f"${metrics['potential_reward_pool_usd']:,}"

    return enriched, overview, {"discovery": disc, "metrics": metrics}


def get_program_detail(handle: str) -> Dict[str, Any]:
    """Program detail panel: scope summary + up to 5 recommendations."""
    from workers.earn.hackerone_intel import resolve_program_intel
    from workers.earn.program_report import generate_recommendations

    cached, _ = _load_cache()
    record = None
    hlow = handle.lower()
    for p in cached:
        if (p.get("handle") or "").lower() == hlow or (p.get("program") or "").lower() == hlow:
            record = p
            break

    intel = resolve_program_intel(
        record.get("title", handle) if record else handle,
        record.get("url", "") if record else f"https://hackerone.com/{handle}",
        record.get("scope_full", []) if record else [],
        record,
    )

    recs = generate_recommendations(intel)[:5]
    enriched = enrich_program(record or {"handle": handle, "title": intel.name, "targets": {"in_scope": [], "out_of_scope": []}})

    # Prefer saved analysis if present
    safe = re.sub(r"[^\w\- ]", "_", intel.name)[:50]
    intel_path = _BOUNTIES / f"{safe}_intel.json"
    saved_recs = []
    if intel_path.is_file():
        try:
            data = json.loads(intel_path.read_text(encoding="utf-8"))
            saved_recs = (data.get("recommendations") or [])[:5]
        except Exception:
            pass

    return {
        "handle": intel.handle,
        "title": intel.name,
        "description": intel.website or intel.url,
        "platform": "HackerOne",
        "bounty_display": intel.bounty_range_display,
        "scope_summary": f"{len(intel.in_scope)} in-scope, {len(intel.out_of_scope)} out-of-scope assets",
        "in_scope_count": len(intel.in_scope),
        "out_scope_count": len(intel.out_of_scope),
        "mobile_targets": [a.identifier for a in intel.mobile_targets],
        "domains": enriched.get("domains") or [],
        "recommendations": saved_recs or [r.to_dict() for r in recs],
        "url": intel.url,
    }


def log_dashboard_event(message: str, socketio: Any = None, level: str = "info") -> None:
    earn_log(socketio, message, level)
