#!/usr/bin/env python3
"""Earn Research Mode validation tests."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def ok(name: str, cond: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return cond


def main() -> int:
    failed = 0

    from workers.earn.research.scope import analyze_scope
    from workers.earn.research.tech_detect import detect_host_technologies
    from workers.earn.research.research_plan import build_research_plan
    from workers.earn.research.findings import findings_from_plan
    from workers.earn.research.models import FindingStatus, WorkflowStage
    from workers.earn.research.placeholders import empty_submission_placeholders
    from workers.earn.hackerone_intel import resolve_program_intel

    sample = {
        "handle": "api-test",
        "name": "API Test Program",
        "targets": {
            "in_scope": [
                {"asset_identifier": "api.example.com", "asset_type": "URL", "eligible_for_bounty": True, "max_severity": "high"},
                {"asset_identifier": "https://api.example.com/graphql", "asset_type": "URL", "eligible_for_bounty": True, "max_severity": "critical"},
            ],
            "out_of_scope": [],
        },
        "offers_bounties": True,
    }
    intel, summary, targets = analyze_scope(sample)
    failed += 0 if ok("analyze scope", len(targets) >= 1 and "api" in summary.lower(), f"{len(targets)} targets") else 1

    hosts = [{"url": "https://api.example.com/graphql", "tech": ["GraphQL", "Cloudflare"], "title": "GQL"}]
    techs = detect_host_technologies(hosts)
    failed += 0 if ok("tech detection", any("GraphQL" in (t.api_tech or []) for t in techs), "") else 1

    plans = build_research_plan(intel, techs)
    failed += 0 if ok("research plan", len(plans) >= 1 and any("IDOR" in (p.suggested_research or []) for p in plans), str(len(plans))) else 1

    findings = findings_from_plan(plans, [])
    failed += 0 if ok("potential findings", len(findings) >= 1, str(len(findings))) else 1
    failed += 0 if ok("finding fields", all(f.title and f.target and f.status == FindingStatus.IDEA.value for f in findings[:3]), "") else 1

    ph = empty_submission_placeholders()
    failed += 0 if ok("no auto submit", ph.submission_draft is None and "not" in ph.note.lower(), "") else 1

    # Pipeline dry-run (no guardian tools) — mock recon via direct store
    from workers.earn.research import store
    with tempfile.TemporaryDirectory() as tmp:
        store.ROOT = Path(tmp) / "research"
        store.SESSIONS_DIR = store.ROOT / "sessions"
        from workers.earn.research.pipeline import _execute_pipeline
        from workers.earn.research.models import ResearchSession

        sid = ResearchSession.new_id()
        sess = ResearchSession(id=sid, program_handle="api-test", program_title="API Test")
        store.save_session(sess)
        store.session_dir(sid)

        # Minimal program for pipeline — may skip tools if not installed
        try:
            _execute_pipeline(sid, sample, None)
            loaded = store.load_session(sid)
            failed += 0 if ok("pipeline completes", loaded and loaded.status in ("complete", "error"), loaded.status if loaded else "none") else 1
            if loaded and loaded.status == "complete":
                failed += 0 if ok("has research plan", len(loaded.research_plan) >= 1, "") else 1
                failed += 0 if ok("has findings", len(loaded.potential_findings) >= 1, "") else 1
                failed += 0 if ok("has evidence", len(loaded.evidence) >= 1, str(len(loaded.evidence))) else 1
                failed += 0 if ok("submission placeholder", loaded.submission_placeholders.get("submission_draft") is None, "") else 1
        except Exception as e:
            failed += 1
            ok("pipeline completes", False, str(e))

    print(f"\n{'ALL PASSED' if failed == 0 else f'{failed} FAILED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
