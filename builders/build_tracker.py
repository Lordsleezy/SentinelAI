"""
In-memory active build state for status queries and Tasks panel.

One active forge build at a time; cleared on completion or failure.
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

_lock = threading.Lock()
_active: Optional[Dict[str, Any]] = None


def _now() -> str:
    return datetime.now().isoformat()


def begin_build(
    task_id: str,
    title: str,
    description: str,
    route: str,
    engine: str,
) -> Dict[str, Any]:
    global _active
    with _lock:
        _active = {
            "task_id": task_id,
            "title": title,
            "description": description[:200],
            "route": route,
            "engine": engine,
            "status": "RUNNING",
            "current_stage": "Planning",
            "progress_percent": 0,
            "files_created": [],
            "started_at": _now(),
            "updated_at": _now(),
            "verification": None,
            "artifact_id": None,
            "launch_ready": False,
            "complete": False,
        }
        return dict(_active)


def update_build(
    *,
    current_stage: Optional[str] = None,
    progress_percent: Optional[int] = None,
    file_created: Optional[str] = None,
    engine: Optional[str] = None,
    verification: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    with _lock:
        if not _active or _active.get("complete"):
            return None
        if current_stage is not None:
            _active["current_stage"] = current_stage
        if progress_percent is not None:
            _active["progress_percent"] = max(0, min(100, int(progress_percent)))
        if file_created:
            name = file_created.replace("\\", "/").split("/")[-1]
            if name and name not in _active["files_created"]:
                _active["files_created"].append(name)
        if engine is not None:
            _active["engine"] = engine
        if verification is not None:
            _active["verification"] = verification
        _active["updated_at"] = _now()
        return dict(_active)


def mark_launch_ready(artifact_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        if not _active:
            return None
        _active["artifact_id"] = artifact_id
        _active["launch_ready"] = True
        _active["updated_at"] = _now()
        return dict(_active)


def finish_build(success: bool, error: Optional[str] = None) -> Optional[Dict[str, Any]]:
    global _active
    with _lock:
        if not _active:
            return None
        _active["status"] = "COMPLETED" if success else "FAILED"
        _active["complete"] = True
        _active["progress_percent"] = 100 if success else _active.get("progress_percent", 0)
        if error:
            _active["error"] = error
        _active["updated_at"] = _now()
        snap = dict(_active)
        _active = None
        return snap


def get_active_build() -> Optional[Dict[str, Any]]:
    with _lock:
        return dict(_active) if _active and not _active.get("complete") else None


def format_build_status(b: Dict[str, Any]) -> str:
    lines = [
        f"**Active build:** {b.get('title', 'Build')}",
        f"- **Route:** {b.get('route', '?')} | **Engine:** {b.get('engine', '?')}",
        f"- **Stage:** {b.get('current_stage', '?')} ({b.get('progress_percent', 0)}%)",
    ]
    files = b.get("files_created") or []
    if files:
        lines.append(f"- **Files ({len(files)}):** {', '.join(files[-8:])}")
    if b.get("verification"):
        lines.append(f"- **Verification:** {b['verification']}")
    if b.get("launch_ready"):
        lines.append("- **Launch:** Ready")
    return "\n".join(lines)
