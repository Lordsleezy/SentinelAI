"""Goal engine — persistent goals and state transitions."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.sentinelvision.audit import audit_log
from core.sentinelvision.types import Goal, GoalStatus, utc_now

_ROOT = Path(__file__).resolve().parents[2]
_DB_PATH = _ROOT / "data" / "sentinelvision" / "goals.db"
_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    with _lock:
        conn = _connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS goals (
                    goal_id TEXT PRIMARY KEY,
                    objective TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    provider_id TEXT,
                    plan_id TEXT,
                    error TEXT,
                    metadata TEXT
                );
                CREATE TABLE IF NOT EXISTS feed (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    message TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    level TEXT DEFAULT 'info',
                    artifact_path TEXT
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    goal_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)
            conn.commit()
        finally:
            conn.close()


class GoalEngine:
    def __init__(self) -> None:
        _init_db()

    def create_goal(self, objective: str, metadata: Optional[Dict[str, Any]] = None) -> Goal:
        goal_id = str(uuid.uuid4())
        goal = Goal(
            goal_id=goal_id,
            objective=objective.strip(),
            status=GoalStatus.QUEUED,
            created_at=utc_now(),
            metadata=metadata or {},
        )
        self._save(goal)
        audit_log("goal_created", goal_id, detail=objective[:200])
        return goal

    def get(self, goal_id: str) -> Optional[Goal]:
        with _lock:
            conn = _connect()
            try:
                row = conn.execute("SELECT * FROM goals WHERE goal_id = ?", (goal_id,)).fetchone()
            finally:
                conn.close()
        return self._row_to_goal(row) if row else None

    def list_goals(self, limit: int = 50) -> List[Goal]:
        with _lock:
            conn = _connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM goals ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
            finally:
                conn.close()
        return [self._row_to_goal(r) for r in rows if r]

    def set_status(
        self,
        goal_id: str,
        status: GoalStatus,
        *,
        error: Optional[str] = None,
        provider_id: Optional[str] = None,
        plan_id: Optional[str] = None,
    ) -> Optional[Goal]:
        goal = self.get(goal_id)
        if not goal:
            return None
        goal.status = status
        if error is not None:
            goal.error = error
        if provider_id is not None:
            goal.provider_id = provider_id
        if plan_id is not None:
            goal.plan_id = plan_id
        if status in (GoalStatus.COMPLETED, GoalStatus.FAILED):
            goal.completed_at = utc_now()
        self._save(goal)
        audit_log("goal_status", goal_id, detail=status.value)
        return goal

    def append_feed(
        self,
        goal_id: str,
        phase: str,
        message: str,
        level: str = "info",
        artifact_path: Optional[str] = None,
    ) -> None:
        with _lock:
            conn = _connect()
            try:
                conn.execute(
                    """INSERT INTO feed (goal_id, phase, message, timestamp, level, artifact_path)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (goal_id, phase, message, utc_now(), level, artifact_path),
                )
                conn.commit()
            finally:
                conn.close()

    def get_feed(self, goal_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        with _lock:
            conn = _connect()
            try:
                rows = conn.execute(
                    """SELECT goal_id, phase, message, timestamp, level, artifact_path
                       FROM feed WHERE goal_id = ? ORDER BY id DESC LIMIT ?""",
                    (goal_id, limit),
                ).fetchall()
            finally:
                conn.close()
        return [dict(r) for r in reversed(rows)]

    def _save(self, goal: Goal) -> None:
        meta = json.dumps(goal.metadata or {})
        with _lock:
            conn = _connect()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO goals
                       (goal_id, objective, status, created_at, completed_at,
                        provider_id, plan_id, error, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        goal.goal_id,
                        goal.objective,
                        goal.status.value if isinstance(goal.status, GoalStatus) else goal.status,
                        goal.created_at,
                        goal.completed_at,
                        goal.provider_id,
                        goal.plan_id,
                        goal.error,
                        meta,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    @staticmethod
    def _row_to_goal(row: sqlite3.Row) -> Goal:
        meta = {}
        if row["metadata"]:
            try:
                meta = json.loads(row["metadata"])
            except json.JSONDecodeError:
                pass
        return Goal(
            goal_id=row["goal_id"],
            objective=row["objective"],
            status=GoalStatus(row["status"]),
            created_at=row["created_at"],
            completed_at=row["completed_at"],
            provider_id=row["provider_id"],
            plan_id=row["plan_id"],
            error=row["error"],
            metadata=meta,
        )
