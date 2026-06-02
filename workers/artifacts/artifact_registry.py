"""
workers/artifacts/artifact_registry.py — Sentinel Artifact Registry

Tracks everything Sentinel creates: apps, scripts, reports, analyses, exports.

Storage: memory/vault/artifacts/registry.json  (rolling 100 entries)
Events:  artifact_created  (via existing Socket.IO)
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_REGISTRY_PATH = (
    Path(__file__).parent.parent.parent / "memory" / "vault" / "artifacts" / "registry.json"
)
_LOCK     = threading.Lock()
_registry: Dict[str, Dict] = {}
_loaded   = False
_MAX      = 100


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    with _LOCK:
        if _loaded:
            return
        try:
            _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
            if _REGISTRY_PATH.exists():
                with open(_REGISTRY_PATH, encoding="utf-8") as f:
                    data = json.load(f)
                for item in (data if isinstance(data, list) else data.values()):
                    _registry[item["id"]] = item
        except Exception as e:
            logger.debug("[ARTIFACTS] Load error: %s", e)
        _loaded = True


def _persist() -> None:
    try:
        entries = sorted(_registry.values(), key=lambda x: x.get("timestamp", ""))
        entries = entries[-_MAX:]
        _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
    except Exception as e:
        logger.error("[ARTIFACTS] Persist error: %s", e)


def _emit(event: str, payload: Dict) -> None:
    try:
        from desktop_app import socketio
        if socketio:
            socketio.emit(event, payload, broadcast=True)
    except Exception:
        pass


def _now() -> str:
    return datetime.now().isoformat()


def _derive_launch_command(entry_point: str, output_dir: str) -> str:
    """Derive a sensible launch command based on the entry_point file type."""
    if not entry_point:
        return ""
    p = Path(entry_point)
    ext = p.suffix.lower()
    if ext == ".py":
        return f"python \"{entry_point}\""
    if ext in (".exe", ".bat", ".cmd"):
        return f"\"{entry_point}\""
    if ext in (".html", ".htm"):
        return f"start \"{entry_point}\""
    if ext == ".js":
        return f"node \"{entry_point}\""
    if ext == ".sh":
        return f"bash \"{entry_point}\""
    return f"\"{entry_point}\""


# ── Public API ───────────────────────────────────────────────────────────────

def register_artifact(
    task: str,
    entry_point: str = "",
    output_dir: str = "",
    files: Optional[List[str]] = None,
    launch_command: str = "",
    task_id: Optional[str] = None,
    project_id: Optional[str] = None,
    artifact_type: str = "app",
) -> Dict:
    """
    Register a newly created artifact.

    Args:
        task:           Human-readable label, e.g. "Calculator"
        entry_point:    Main file path (absolute or relative).
        output_dir:     Root directory of the artifact.
        files:          List of files produced.
        launch_command: Command to run the artifact.  Auto-derived if blank.
        task_id:        ID of the parent Task (if any).
        project_id:     ID of the parent Project (if any).
        artifact_type:  "app", "script", "report", "analysis", "export".

    Returns:
        Artifact dict.
    """
    _ensure_loaded()
    if not launch_command and entry_point:
        launch_command = _derive_launch_command(entry_point, output_dir)
    artifact_id = "art_" + uuid.uuid4().hex[:10]
    artifact: Dict = {
        "id":             artifact_id,
        "task":           task,
        "entry_point":    entry_point,
        "output_dir":     output_dir,
        "files":          files or ([entry_point] if entry_point else []),
        "launch_command": launch_command,
        "artifact_type":  artifact_type,
        "task_id":        task_id,
        "project_id":     project_id,
        "timestamp":      _now(),
    }
    with _LOCK:
        _registry[artifact_id] = artifact
        _persist()
    logger.info("[ARTIFACTS] Registered: %s  entry=%s", artifact_id, entry_point)
    _emit("artifact_created", artifact)
    return dict(artifact)


def list_artifacts(
    limit: int = 20,
    project_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> List[Dict]:
    """Return artifacts, most recent first."""
    _ensure_loaded()
    items = sorted(_registry.values(), key=lambda x: x.get("timestamp", ""), reverse=True)
    if project_id:
        items = [a for a in items if a.get("project_id") == project_id]
    if task_id:
        items = [a for a in items if a.get("task_id") == task_id]
    return [dict(a) for a in items[:limit]]


def get_artifact(artifact_id: str) -> Optional[Dict]:
    _ensure_loaded()
    a = _registry.get(artifact_id)
    return dict(a) if a else None


def get_latest_artifact() -> Optional[Dict]:
    items = list_artifacts(limit=1)
    return items[0] if items else None


def get_artifact_by_task(task_hint: str) -> Optional[Dict]:
    """Find the most recent artifact whose task name contains task_hint."""
    _ensure_loaded()
    hint = task_hint.lower()
    candidates = sorted(
        [a for a in _registry.values() if hint in a.get("task", "").lower()],
        key=lambda x: x.get("timestamp", ""),
        reverse=True,
    )
    return dict(candidates[0]) if candidates else None


def launch_artifact(artifact: Dict) -> Dict:
    """
    Launch an artifact by running its stored launch_command.

    Returns:
        {"ok": True, "message": ...} or {"ok": False, "error": ...}
    """
    cmd = artifact.get("launch_command", "")
    entry = artifact.get("entry_point", "")

    if not cmd:
        return {"ok": False, "error": "No launch command stored for this artifact."}

    # Safety: check the entry point exists (if it points to a file)
    if entry and not Path(entry).exists():
        return {
            "ok": False,
            "error": f"Entry point not found: {entry}",
        }

    try:
        ext = Path(entry).suffix.lower() if entry else ""
        if ext == ".html":
            import webbrowser
            webbrowser.open(Path(entry).as_uri())
            return {"ok": True, "message": f"Opened {entry} in browser."}

        # Detach so the launched process doesn't block Sentinel
        kwargs: Dict = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        subprocess.Popen(
            cmd,
            shell=True,
            cwd=artifact.get("output_dir") or None,
            **kwargs,
        )
        return {"ok": True, "message": f"Launched: {cmd}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def launch_latest() -> Dict:
    artifact = get_latest_artifact()
    if not artifact:
        return {"ok": False, "error": "No artifacts registered yet."}
    return launch_artifact(artifact)
