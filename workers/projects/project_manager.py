"""
workers/projects/project_manager.py — Sentinel Project Manager

Lightweight organizational layer.  Projects are labels that tasks and artifacts
can reference.  NO memory rewrite, NO vector DB changes.

Storage: memory/vault/projects/projects.json
Events:  project_created, project_updated (via existing Socket.IO)
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_PROJECTS_PATH = Path(__file__).parent.parent.parent / "memory" / "vault" / "projects" / "projects.json"
_LOCK          = threading.Lock()
_projects: Dict[str, Dict] = {}
_loaded        = False

_DEFAULT_COLORS = [
    "#00ff88", "#00cfff", "#ff6b6b", "#ffd700",
    "#da70d6", "#ff8c00", "#7fff00", "#1e90ff",
]


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    with _LOCK:
        if _loaded:
            return
        try:
            _PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
            if _PROJECTS_PATH.exists():
                with open(_PROJECTS_PATH, encoding="utf-8") as f:
                    data = json.load(f)
                for p in (data if isinstance(data, list) else data.values()):
                    _projects[p["id"]] = p
        except Exception as e:
            logger.debug("[PROJECTS] Load error: %s", e)
        _loaded = True


def _persist() -> None:
    try:
        _PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_PROJECTS_PATH, "w", encoding="utf-8") as f:
            json.dump(list(_projects.values()), f, indent=2)
    except Exception as e:
        logger.error("[PROJECTS] Persist error: %s", e)


def _emit(event: str, payload: Dict) -> None:
    try:
        from desktop_app import socketio
        if socketio:
            socketio.emit(event, payload)
    except Exception:
        pass


def _now() -> str:
    return datetime.now().isoformat()


def _pick_color() -> str:
    used = {p.get("color") for p in _projects.values()}
    for c in _DEFAULT_COLORS:
        if c not in used:
            return c
    return "#888888"


# ── Public API ───────────────────────────────────────────────────────────────

def create_project(name: str, color: Optional[str] = None) -> Dict:
    """
    Create a new project.

    Args:
        name:  Display name, e.g. "Sentinel Prime"
        color: Hex color for UI badge.  Auto-assigned if omitted.

    Returns:
        Project dict with keys: id, name, color, created_at, updated_at.
    """
    _ensure_loaded()
    with _LOCK:
        # Prevent duplicates by name
        for p in _projects.values():
            if p.get("name", "").lower() == name.strip().lower():
                return dict(p)
        proj_id = "proj_" + uuid.uuid4().hex[:8]
        now = _now()
        project: Dict = {
            "id":         proj_id,
            "name":       name.strip(),
            "color":      color or _pick_color(),
            "created_at": now,
            "updated_at": now,
        }
        _projects[proj_id] = project
        _persist()
    logger.info("[PROJECTS] Created: %s (%s)", proj_id, name)
    _emit("project_created", project)
    return dict(project)


def list_projects() -> List[Dict]:
    _ensure_loaded()
    return sorted(
        (_projects.values()),
        key=lambda p: p.get("created_at", ""),
        reverse=True,
    )


def get_project(project_id: str) -> Optional[Dict]:
    _ensure_loaded()
    p = _projects.get(project_id)
    return dict(p) if p else None


def get_or_create_project(name: str) -> Dict:
    """Return existing project by name or create a new one."""
    _ensure_loaded()
    for p in _projects.values():
        if p.get("name", "").lower() == name.strip().lower():
            return dict(p)
    return create_project(name)


def update_project(project_id: str, name: Optional[str] = None,
                   color: Optional[str] = None) -> Optional[Dict]:
    _ensure_loaded()
    with _LOCK:
        p = _projects.get(project_id)
        if not p:
            return None
        if name is not None:
            p["name"] = name.strip()
        if color is not None:
            p["color"] = color
        p["updated_at"] = _now()
        _persist()
    _emit("project_updated", p)
    return dict(p)


def delete_project(project_id: str) -> bool:
    _ensure_loaded()
    with _LOCK:
        if project_id not in _projects:
            return False
        del _projects[project_id]
        _persist()
    return True
