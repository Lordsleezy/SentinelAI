"""Earn Research pipeline — Accept → Scope → Recon → Tech → Plan → Findings → Evidence."""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from workers.earn.research.findings import findings_from_plan
from workers.earn.research.guardian_recon import run_controlled_recon
from workers.earn.research.models import ResearchSession, SubmissionPlaceholders
from workers.earn.research.placeholders import empty_submission_placeholders
from workers.earn.research.research_plan import build_research_plan
from workers.earn.research.scope import analyze_scope
from workers.earn.research.store import (
    add_evidence,
    append_log,
    load_session,
    save_session,
    session_dir,
)
from workers.earn.research.tech_detect import detect_host_technologies

logger = logging.getLogger("sentinel.earn.research")

_active: Dict[str, threading.Thread] = {}


def _emit(socketio: Any, msg: str, level: str = "info") -> None:
    logger.info("[EARN Research] %s", msg)
    if socketio:
        try:
            socketio.emit("log_event", {"type": "earn", "level": level, "message": f"[EARN Research] {msg}"})
            socketio.emit("earn_research_update", {"message": msg})
        except Exception:
            pass


def run_research_pipeline(
    program_data: Dict[str, Any],
    socketio: Any = None,
    background: bool = True,
) -> ResearchSession:
    """Start research: Accept Program → Analyze Scope → Launch Research Pipeline."""
    handle = program_data.get("handle") or program_data.get("program") or "unknown"
    title = program_data.get("title") or program_data.get("name") or handle

    session = ResearchSession(
        id=ResearchSession.new_id(),
        program_handle=handle,
        program_title=title,
        status="running",
        submission_placeholders=empty_submission_placeholders().to_dict(),
    )
    save_session(session)
    session_dir(session.id)

    def _run() -> None:
        try:
            _execute_pipeline(session.id, program_data, socketio)
        except Exception as e:
            s = load_session(session.id)
            if s:
                s.status = "error"
                s.error = str(e)
                append_log(s, f"Pipeline error: {e}")
                save_session(s)
            _emit(socketio, f"Research failed: {e}", "error")

    if background:
        t = threading.Thread(target=_run, daemon=True, name=f"earn-research-{session.id}")
        _active[session.id] = t
        t.start()
    else:
        _run()
        session = load_session(session.id) or session
    return session


def _execute_pipeline(session_id: str, program_data: Dict[str, Any], socketio: Any) -> None:
    session = load_session(session_id)
    if not session:
        return

    _emit(socketio, f"Accept Program: {session.program_title}")
    append_log(session, "Phase 1: Program accepted")

    _emit(socketio, "Analyze Scope…")
    intel, summary, targets = analyze_scope(program_data)
    session.scope_summary = summary
    session.in_scope_assets = [a.identifier for a in intel.in_scope if a.eligible_for_bounty]
    session.targets_probed = targets
    append_log(session, f"Phase 2: Scope analyzed — {len(targets)} probe target(s)")
    save_session(session)

    add_evidence(session, "note", json.dumps(intel.to_dict(), indent=2)[:50_000], "scope_intel.json")

    _emit(socketio, "Launch Research Pipeline — Guardian recon (in-scope only)…")
    recon = run_controlled_recon(session_id, intel, targets, socketio)
    session.recon_outputs = recon
    append_log(session, f"Phase 3: Recon complete — tools: {recon.get('tools_run')}")
    save_session(session)

    add_evidence(session, "log", json.dumps(recon, indent=2)[:100_000], "recon_summary.json")

    _emit(socketio, "Technology detection…")
    host_tech = detect_host_technologies(recon.get("hosts") or [])
    session.technologies = [h.to_dict() for h in host_tech]
    append_log(session, f"Phase 4: {len(host_tech)} host(s) fingerprinted")
    save_session(session)

    _emit(socketio, "Generating Research Plan…")
    plans = build_research_plan(intel, host_tech)
    session.research_plan = [p.to_dict() for p in plans]
    append_log(session, f"Phase 5: {len(plans)} research plan item(s)")
    save_session(session)

    _emit(socketio, "Creating Potential Findings…")
    pfindings = findings_from_plan(plans, recon.get("nuclei_findings") or [])
    session.potential_findings = [f.to_dict() for f in pfindings]
    append_log(session, f"Phase 6: {len(pfindings)} potential finding(s) — NOT auto-submitted")
    save_session(session)

    # Evidence scaffolding
    add_evidence(session, "note", "Research evidence vault ready. Add requests/responses/screenshots via API.", "README.txt")
    placeholders = empty_submission_placeholders()
    session.submission_placeholders = placeholders.to_dict()

    session.status = "complete"
    session.updated_at = datetime.now(timezone.utc).isoformat()
    append_log(session, "Pipeline complete — awaiting human review")
    save_session(session)
    _emit(socketio, f"Research complete: {len(pfindings)} potential finding(s)", "success")


def get_research_session(session_id: str) -> Optional[ResearchSession]:
    return load_session(session_id)
