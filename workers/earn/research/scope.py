"""Analyze in-scope assets from program data."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Set, Tuple
from urllib.parse import urlparse

from workers.earn.hackerone_intel import ProgramIntel, ScopeAsset, resolve_program_intel


def analyze_scope(program_data: Dict[str, Any]) -> Tuple[ProgramIntel, str, List[str]]:
    """Return intel, summary text, and probe targets (in-scope only)."""
    intel = resolve_program_intel(
        title=program_data.get("title") or program_data.get("name") or "",
        url=program_data.get("url") or "",
        scope_hints=program_data.get("scope_full") or program_data.get("scope"),
        program_data=program_data,
    )
    in_scope_ids = [a.identifier for a in intel.in_scope if a.eligible_for_bounty]
    summary = (
        f"{intel.name}: {len(intel.in_scope)} in-scope, {len(intel.out_of_scope)} out-of-scope. "
        f"Mobile: {len(intel.mobile_targets)}, Web/API surfaces mapped."
    )
    targets = _probe_targets_from_intel(intel)
    return intel, summary, targets


def _probe_targets_from_intel(intel: ProgramIntel, max_targets: int = 25) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []

    def add(url: str) -> None:
        u = url.strip()
        if not u or u in seen:
            return
        seen.add(u)
        out.append(u)

    for asset in intel.in_scope:
        if not asset.eligible_for_bounty:
            continue
        ident = (asset.identifier or "").strip()
        if not ident:
            continue
        if ident.startswith(("http://", "https://")):
            add(ident)
        elif asset.category == "api" or "." in ident:
            host = ident.split("/")[0]
            add(f"https://{host}")
        elif asset.category == "mobile":
            continue
        else:
            add(f"https://{ident}")

    # Domain roots for subfinder (in-scope domains only)
    for asset in intel.in_scope:
        ident = asset.identifier
        if "." in ident and not ident.startswith("http"):
            host = ident.split("/")[0].lower()
            if re.match(r"^[a-z0-9][a-z0-9.-]+\.[a-z]{2,}$", host):
                add(f"https://{host}")

    return out[:max_targets]
