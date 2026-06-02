"""
workers/task_manager.py — Sentinel Task Manager

Every major action becomes a tracked task with persistent state,
progress updates, and live Socket.IO streaming.

States:  PENDING → RUNNING → COMPLETED | FAILED | CANCELLED
         RUNNING → WAITING_FOR_APPROVAL | WAITING_FOR_USER → RUNNING

Storage: memory/vault/tasks/tasks.json  (rolling 200-entry window)
Events:  task_created, task_update  (broadcast via existing Socket.IO)
RAM:     < 5 MB overhead (in-memory dict mirrors JSON file)
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

PENDING             = "PENDING"
RUNNING             = "RUNNING"
WAITING_APPROVAL    = "WAITING_FOR_APPROVAL"
WAITING_USER        = "WAITING_FOR_USER"
COMPLETED           = "COMPLETED"
FAILED              = "FAILED"
CANCELLED           = "CANCELLED"

TERMINAL_STATES = {COMPLETED, FAILED, CANCELLED}

_TASKS_PATH = Path(__file__).parent.parent / "memory" / "vault" / "tasks" / "tasks.json"
_MAX_TASKS  = 200
_LOCK       = threading.Lock()

# In-memory cache (mirrors file)
_tasks: Dict[str, Dict] = {}
_loaded = False


# ── Storage helpers ──────────────────────────────────────────────────────────

def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    with _LOCK:
        if _loaded:
            return
        _tasks_path = _TASKS_PATH
        try:
            _tasks_path.parent.mkdir(parents=True, exist_ok=True)
            if _tasks_path.exists():
                with open(_tasks_path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for t in data:
                        _tasks[t["id"]] = t
                elif isinstance(data, dict):
                    _tasks.update(data)
        except Exception as e:
            logger.debug("[TASK] Load error: %s", e)
        _loaded = True


def _persist() -> None:
    """Write current in-memory tasks to disk (most recent _MAX_TASKS)."""
    try:
        entries = sorted(_tasks.values(), key=lambda t: t.get("created_at", ""))
        entries = entries[-_MAX_TASKS:]
        _TASKS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_TASKS_PATH, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
    except Exception as e:
        logger.error("[TASK] Persist error: %s", e)


def _emit_task(event: str, task: Dict) -> None:
    """Emit a Socket.IO event for a task update. No-op if socketio unavailable."""
    try:
        from desktop_app import socketio
        if socketio:
            socketio.emit(event, _public(task))
    except Exception as e:
        logger.debug("[TASK] Emit '%s' failed: %s", event, e)


def _public(task: Dict) -> Dict:
    """Return a copy of the task safe for JSON serialization."""
    return {k: v for k, v in task.items()}


def _now() -> str:
    return datetime.now().isoformat()


# ── Public API ───────────────────────────────────────────────────────────────

def create_task(
    title: str,
    source: str = "system",
    project_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    status: str = PENDING,
) -> Dict:
    """
    Create and persist a new task. Emits 'task_created'.

    Args:
        title:      Human-readable task title, e.g. "Guardian Scan - sentinelprime.org"
        source:     Worker that owns this task: "guardian", "earn", "forge", "system", …
        project_id: Optional project this task belongs to.
        metadata:   Arbitrary extra data (target URL, scope, etc.).
        status:     Initial status (default PENDING).

    Returns:
        Task dict.
    """
    _ensure_loaded()
    task_id = "task_" + uuid.uuid4().hex[:10]
    now = _now()
    task: Dict[str, Any] = {
        "id":             task_id,
        "title":          title,
        "source":         source,
        "status":         status,
        "progress":       0,
        "created_at":     now,
        "updated_at":     now,
        "error":          None,
        "result_summary": None,
        "project_id":     project_id,
        "metadata":       metadata or {},
    }
    with _LOCK:
        _tasks[task_id] = task
        _persist()
    logger.info("[TASK] Created: %s (%s) source=%s", task_id, title, source)
    _emit_task("task_created", task)
    return dict(task)


def update_task(
    task_id: str,
    status: Optional[str] = None,
    progress: Optional[int] = None,
    error: Optional[str] = None,
    result_summary: Optional[str] = None,
    metadata_update: Optional[Dict] = None,
) -> Optional[Dict]:
    """
    Update task fields. Emits 'task_update'.

    Args:
        task_id:        ID returned by create_task().
        status:         New status (see constants above).
        progress:       0–100.
        error:          Error message if status=FAILED.
        result_summary: Short human summary on completion.
        metadata_update: Dict to merge into task.metadata.

    Returns:
        Updated task dict, or None if not found.
    """
    _ensure_loaded()
    with _LOCK:
        task = _tasks.get(task_id)
        if not task:
            logger.warning("[TASK] update_task: %s not found", task_id)
            return None
        if status is not None:
            task["status"] = status
        if progress is not None:
            task["progress"] = max(0, min(100, int(progress)))
        if error is not None:
            task["error"] = error
        if result_summary is not None:
            task["result_summary"] = result_summary
        if metadata_update:
            task.setdefault("metadata", {}).update(metadata_update)
        task["updated_at"] = _now()
        _persist()
    logger.info("[TASK] Updated: %s status=%s progress=%s",
                task_id, task.get("status"), task.get("progress"))
    _emit_task("task_update", task)
    return dict(task)


def get_task(task_id: str) -> Optional[Dict]:
    _ensure_loaded()
    t = _tasks.get(task_id)
    return dict(t) if t else None


def list_tasks(
    status: Optional[str] = None,
    source: Optional[str] = None,
    project_id: Optional[str] = None,
    limit: int = 50,
) -> List[Dict]:
    """Return tasks, most recent first, with optional filters."""
    _ensure_loaded()
    tasks = sorted(_tasks.values(), key=lambda t: t.get("created_at", ""), reverse=True)
    if status:
        tasks = [t for t in tasks if t.get("status") == status]
    if source:
        tasks = [t for t in tasks if t.get("source") == source]
    if project_id:
        tasks = [t for t in tasks if t.get("project_id") == project_id]
    return [dict(t) for t in tasks[:limit]]


def cancel_task(task_id: str) -> Optional[Dict]:
    return update_task(task_id, status=CANCELLED)


def running_tasks() -> List[Dict]:
    return list_tasks(status=RUNNING)


def recent_tasks(limit: int = 20) -> List[Dict]:
    return list_tasks(limit=limit)


# ── Context manager helper for wrapping any callable ─────────────────────────

class TaskContext:
    """
    Lightweight context manager so workers can be wrapped without rewriting:

        with TaskContext("Build Calculator", source="forge") as ctx:
            result = engine.build_app(description)
            ctx.complete(result_summary="Calculator built successfully")

    On __exit__ with exception: task set to FAILED automatically.
    """

    def __init__(
        self,
        title: str,
        source: str = "system",
        project_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ):
        self.title      = title
        self.source     = source
        self.project_id = project_id
        self.metadata   = metadata or {}
        self.task_id: Optional[str] = None
        self._task: Optional[Dict]  = None

    def __enter__(self) -> "TaskContext":
        self._task = create_task(
            title=self.title,
            source=self.source,
            project_id=self.project_id,
            metadata=self.metadata,
            status=RUNNING,
        )
        self.task_id = self._task["id"]
        return self

    def progress(self, pct: int, summary: str = "") -> None:
        update_task(self.task_id, progress=pct,
                    result_summary=summary or None)

    def complete(self, result_summary: str = "", artifact_id: Optional[str] = None) -> None:
        meta = {}
        if artifact_id:
            meta["artifact_id"] = artifact_id
        update_task(self.task_id, status=COMPLETED, progress=100,
                    result_summary=result_summary,
                    metadata_update=meta if meta else None)

    def fail(self, error: str) -> None:
        update_task(self.task_id, status=FAILED, error=error)

    def wait_approval(self) -> None:
        update_task(self.task_id, status=WAITING_APPROVAL)

    def resume(self) -> None:
        update_task(self.task_id, status=RUNNING)

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is not None and self.task_id:
            task = get_task(self.task_id)
            if task and task.get("status") not in TERMINAL_STATES:
                update_task(self.task_id, status=FAILED, error=str(exc_val))
        return False   # do not suppress exceptions


# ── Singleton getter (for convenience) ───────────────────────────────────────

class _TaskManager:
    """Thin facade over module-level functions (keeps old import style working)."""
    create_task   = staticmethod(create_task)
    update_task   = staticmethod(update_task)
    get_task      = staticmethod(get_task)
    list_tasks    = staticmethod(list_tasks)
    cancel_task   = staticmethod(cancel_task)
    running_tasks = staticmethod(running_tasks)
    recent_tasks  = staticmethod(recent_tasks)
    TaskContext   = TaskContext

    # State constants
    PENDING          = PENDING
    RUNNING          = RUNNING
    WAITING_APPROVAL = WAITING_APPROVAL
    WAITING_USER     = WAITING_USER
    COMPLETED        = COMPLETED
    FAILED           = FAILED
    CANCELLED        = CANCELLED


_instance: Optional[_TaskManager] = None


def get_task_manager() -> _TaskManager:
    global _instance
    if _instance is None:
        _instance = _TaskManager()
    return _instance
