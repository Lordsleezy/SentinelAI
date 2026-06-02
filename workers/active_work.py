"""
Resolve the user's currently active work (build > guardian > earn) for status queries.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def _format_guardian() -> Optional[str]:
    try:
        from desktop_app import live_workers
        g = live_workers.get("guardian") or {}
        if g.get("status") in ("scanning", "running", "busy"):
            task = g.get("current_task") or "security scan"
            return (
                f"**Active Guardian scan**\n"
                f"- **Status:** {g.get('status', 'running')}\n"
                f"- **Task:** {task}"
            )
    except Exception:
        pass
    try:
        from desktop_app import get_guardian_brain
        brain = get_guardian_brain()
        st = brain.get_status()
        if st.get("running") or st.get("status") == "running":
            return (
                f"**Active Guardian scan**\n"
                f"- **Target:** {st.get('target', 'unknown')}\n"
                f"- **Stage:** {st.get('stage', 'in progress')}"
            )
    except Exception:
        pass
    return None


def _format_earn() -> Optional[str]:
    try:
        from workers.task_manager import list_tasks, RUNNING
        tasks = list_tasks(status=RUNNING, source="earn", limit=3)
        if not tasks:
            return None
        t = tasks[0]
        stage = t.get("current_stage") or t.get("result_summary") or "analyzing"
        return (
            f"**Active Earn analysis**\n"
            f"- **Program:** {t.get('title', 'bounty')}\n"
            f"- **Stage:** {stage} ({t.get('progress', 0)}%)"
        )
    except Exception:
        return None


def get_active_work_response() -> Optional[str]:
    """Human-readable status for the highest-priority active task."""
    try:
        from builders.build_tracker import format_build_status, get_active_build
        b = get_active_build()
        if b:
            return format_build_status(b)
    except Exception:
        pass

    g = _format_guardian()
    if g:
        return g

    e = _format_earn()
    if e:
        return e

    return None


def is_status_query(message: str) -> bool:
    lower = message.lower().strip().rstrip("?").strip()
    if not lower:
        return False
    exact = {
        "status", "update", "updates", "progress",
        "how is the build going", "how's the build going",
        "build status", "build progress", "build update",
    }
    if lower in exact:
        return True
    phrases = (
        "any updates",
        "do you have any updates",
        "how is the build",
        "how's the build",
        "what's the build status",
        "whats the build status",
        "current build",
        "build going",
    )
    return any(p in lower for p in phrases)
