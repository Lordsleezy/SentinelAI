"""Mission engine — persistent goals with progress, tasks, blockers, dependencies."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sentinel.missions")

_ROOT = Path(__file__).resolve().parents[2]
_DB_PATH = _ROOT / "data" / "missions" / "missions.db"
_lock = threading.Lock()

MISSION_TEMPLATES = {
    "launch_sentinel": "Launch Sentinel AI",
    "configure_stripe": "Configure Stripe",
    "connect_supabase": "Connect Supabase",
    "deploy_website": "Deploy Website",
}


def _utc() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _match_template(objective: str) -> Optional[str]:
    lower = objective.lower()
    for mid, title in MISSION_TEMPLATES.items():
        if title.lower() in lower or mid.replace("_", " ") in lower:
            return title
    return None


class MissionEngine:
    def __init__(self) -> None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with _lock:
            conn = sqlite3.connect(str(_DB_PATH))
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS missions (
                        mission_id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        goal TEXT NOT NULL,
                        status TEXT NOT NULL,
                        progress REAL DEFAULT 0,
                        current_task TEXT,
                        blockers TEXT,
                        dependencies TEXT,
                        completion_state TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        metadata TEXT
                    );
                    CREATE TABLE IF NOT EXISTS mission_tasks (
                        task_id TEXT PRIMARY KEY,
                        mission_id TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        ref_id TEXT,
                        description TEXT,
                        status TEXT,
                        created_at TEXT NOT NULL
                    );
                """)
                conn.commit()
            finally:
                conn.close()

    def create_mission(
        self,
        title: str,
        *,
        goal: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        mission_id = str(uuid.uuid4())
        now = _utc()
        mission = {
            "mission_id": mission_id,
            "title": title,
            "goal": goal or title,
            "status": "active",
            "progress": 0.0,
            "current_task": "",
            "blockers": [],
            "dependencies": dependencies or [],
            "completion_state": "not_started",
            "created_at": now,
            "updated_at": now,
            "metadata": metadata or {},
        }
        self._save(mission)
        return mission

    def resolve_or_create(self, objective: str) -> Dict[str, Any]:
        """Find active mission by title/goal or create from template."""
        existing = self.find_by_objective(objective)
        if existing:
            return existing
        title = _match_template(objective) or objective[:120]
        return self.create_mission(title, goal=objective)

    def find_by_objective(self, objective: str) -> Optional[Dict[str, Any]]:
        q = objective.lower().strip()
        for m in self.list_missions(status="active"):
            if q in (m.get("goal") or "").lower() or q in (m.get("title") or "").lower():
                return m
        return None

    def attach_vision_goal(self, mission_id: str, goal_id: str, objective: str) -> Dict[str, Any]:
        return self.attach_task(mission_id, "vision_goal", goal_id, objective)

    def attach_task(
        self,
        mission_id: str,
        kind: str,
        ref_id: str,
        description: str,
    ) -> Dict[str, Any]:
        task_id = str(uuid.uuid4())
        now = _utc()
        with _lock:
            conn = sqlite3.connect(str(_DB_PATH))
            try:
                conn.execute(
                    """INSERT INTO mission_tasks
                       (task_id, mission_id, kind, ref_id, description, status, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (task_id, mission_id, kind, ref_id, description, "active", now),
                )
                conn.commit()
            finally:
                conn.close()
        self.update_mission(
            mission_id,
            current_task=description[:200],
            completion_state="in_progress",
        )
        return {"task_id": task_id, "mission_id": mission_id}

    def update_mission(self, mission_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        m = self.get_mission(mission_id)
        if not m:
            return None
        for k, v in fields.items():
            if k in ("blockers", "dependencies") and isinstance(v, list):
                m[k] = v
            elif k in m:
                m[k] = v
        m["updated_at"] = _utc()
        if m.get("progress", 0) >= 100:
            m["status"] = "completed"
            m["completion_state"] = "completed"
        self._save(m)
        return m

    def on_vision_goal_completed(self, goal_id: str, objective: str, success: bool) -> None:
        with _lock:
            conn = sqlite3.connect(str(_DB_PATH))
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT mission_id FROM mission_tasks WHERE ref_id = ? AND kind = 'vision_goal'",
                    (goal_id,),
                ).fetchone()
            finally:
                conn.close()
        if not row:
            mid = self.resolve_or_create(objective).get("mission_id")
            self.attach_vision_goal(mid, goal_id, objective)
            m = self.get_mission(mid)
        else:
            m = self.get_mission(row["mission_id"])
        if not m:
            return
        progress = min(100.0, (m.get("progress") or 0) + (25.0 if success else 0))
        blockers = list(m.get("blockers") or [])
        if not success:
            blockers.append(f"Vision goal failed: {objective[:80]}")
        self.update_mission(
            m["mission_id"],
            progress=progress,
            blockers=blockers,
            completion_state="completed" if progress >= 100 else "in_progress",
            current_task="" if progress >= 100 else m.get("current_task"),
        )

    def get_mission(self, mission_id: str) -> Optional[Dict[str, Any]]:
        with _lock:
            conn = sqlite3.connect(str(_DB_PATH))
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT * FROM missions WHERE mission_id = ?", (mission_id,)
                ).fetchone()
                return self._row_to_mission(row) if row else None
            finally:
                conn.close()

    def list_missions(self, *, status: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM missions"
        params: tuple = ()
        if status:
            sql += " WHERE status = ?"
            params = (status,)
        sql += " ORDER BY updated_at DESC"
        with _lock:
            conn = sqlite3.connect(str(_DB_PATH))
            conn.row_factory = sqlite3.Row
            try:
                return [self._row_to_mission(r) for r in conn.execute(sql, params).fetchall()]
            finally:
                conn.close()

    def _row_to_mission(self, row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        for field in ("blockers", "dependencies", "metadata"):
            try:
                d[field] = json.loads(d.get(field) or "[]" if field != "metadata" else "{}")
            except Exception:
                d[field] = [] if field != "metadata" else {}
        return d

    def _save(self, mission: Dict[str, Any]) -> None:
        with _lock:
            conn = sqlite3.connect(str(_DB_PATH))
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO missions
                       (mission_id, title, goal, status, progress, current_task, blockers,
                        dependencies, completion_state, created_at, updated_at, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        mission["mission_id"],
                        mission["title"],
                        mission["goal"],
                        mission["status"],
                        mission.get("progress", 0),
                        mission.get("current_task", ""),
                        json.dumps(mission.get("blockers", [])),
                        json.dumps(mission.get("dependencies", [])),
                        mission.get("completion_state", "not_started"),
                        mission["created_at"],
                        mission["updated_at"],
                        json.dumps(mission.get("metadata", {})),
                    ),
                )
                conn.commit()
            finally:
                conn.close()


_engine: Optional[MissionEngine] = None


def get_mission_engine() -> MissionEngine:
    global _engine
    if _engine is None:
        _engine = MissionEngine()
    return _engine
