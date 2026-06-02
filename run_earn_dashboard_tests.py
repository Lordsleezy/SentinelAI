#!/usr/bin/env python3
"""Earn Discovery Dashboard tests."""
from __future__ import annotations

import sys


def ok(name: str, cond: bool, detail: str = "") -> bool:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    return cond


def main() -> int:
    failed = 0

    from workers.earn.dashboard_enrich import enrich_program, compute_overview
    from workers.earn.sources.bounty_targets import parse_hackerone_program

    sample = {
        "handle": "twilio",
        "name": "Twilio",
        "offers_bounties": True,
        "submission_state": "open",
        "targets": {
            "in_scope": [
                {"asset_identifier": "api.twilio.com", "asset_type": "URL", "eligible_for_bounty": True, "max_severity": "critical"},
                {"asset_identifier": "SUPERAPP (IOS)", "asset_type": "APPLE_STORE_APP_ID", "eligible_for_bounty": True, "max_severity": "high"},
            ],
            "out_of_scope": [{"asset_identifier": "corp.twilio.com"}],
        },
        "attributes": {"minimum_bounty_table": {"critical": 100}, "maximum_bounty_table": {"critical": 25000}},
    }
    parsed = parse_hackerone_program(sample)
    enriched = enrich_program(parsed, sample)
    failed += 0 if ok("enrich asset counts", enriched.get("asset_count") == 2, str(enriched.get("asset_count"))) else 1
    failed += 0 if ok("enrich flags", enriched.get("has_mobile") and enriched.get("has_api"), "") else 1
    failed += 0 if ok("enrich bounty usd", enriched.get("bounty_max_usd") == 25000, str(enriched.get("bounty_max_usd"))) else 1
    failed += 0 if ok("search blob", "twilio" in enriched.get("search_blob", ""), "") else 1

    ov = compute_overview([enriched])
    failed += 0 if ok("overview counts", ov.get("programs_available") == 1, "") else 1

    from workers.earn.dashboard_service import fetch_dashboard_programs, get_program_detail

    programs, overview, extra = fetch_dashboard_programs(refresh=False, force=False)
    failed += 0 if ok("load programs", len(programs) >= 50, f"{len(programs)} programs") else 1
    failed += 0 if ok("overview fields", "programs_available" in overview, "") else 1
    failed += 0 if ok("metrics", "programs_discovered" in (extra.get("metrics") or {}), "") else 1

    if programs:
        h = programs[0].get("handle") or programs[0].get("program")
        detail = get_program_detail(h)
        failed += 0 if ok("program detail", detail.get("title") and detail.get("in_scope_count") is not None, h) else 1
        failed += 0 if ok("recommendations", isinstance(detail.get("recommendations"), list), str(len(detail.get("recommendations", [])))) else 1

    # Filter simulation
    high = [p for p in programs if (p.get("bounty_max_usd") or 0) >= 2500]
    failed += 0 if ok("high bounty filter sample", len(high) > 0, f"{len(high)}") else 1

    api_only = [p for p in programs if p.get("has_api")]
    failed += 0 if ok("api filter sample", len(api_only) > 0, f"{len(api_only)}") else 1

    print(f"\n{'ALL PASSED' if failed == 0 else f'{failed} FAILED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
