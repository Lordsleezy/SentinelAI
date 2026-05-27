"""
SQLite persistence for SentinelAI workflow orchestration.
"""

import json
from typing import Any, Dict, List, Optional

import db
from .models import ApprovalStatus, WorkflowState, WorkflowStatus


def _json_dump(data: Dict[str, Any]) -> str:
    return json.dumps(data or {}, sort_keys=True)


def _json_load(value: Optional[str]) -> Dict[str, Any]:
    if not value:
        return {}
    try:
        return json.loads(value)
    except Exception:
        return {}


def init_orchestration_tables() -> None:
    """Create orchestration tables without changing existing schemas."""
    with db.get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS orchestration_workflows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_type TEXT NOT NULL,
                goal TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                current_node TEXT DEFAULT 'created',
                assigned_agent TEXT,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                requires_approval INTEGER DEFAULT 1,
                approval_status TEXT DEFAULT 'pending',
                state_json TEXT DEFAULT '{}',
                result_json TEXT DEFAULT '{}',
                error_message TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS workflow_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id INTEGER NOT NULL,
                node_name TEXT NOT NULL,
                status TEXT NOT NULL,
                state_json TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (workflow_id) REFERENCES orchestration_workflows(id)
            );

            CREATE TABLE IF NOT EXISTS orchestration_execution_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id INTEGER,
                agent_name TEXT,
                event_type TEXT NOT NULL,
                detail TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (workflow_id) REFERENCES orchestration_workflows(id)
            );

            CREATE TABLE IF NOT EXISTS orchestration_agent_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                memory_key TEXT NOT NULL,
                memory_json TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(agent_name, memory_key)
            );

            CREATE TABLE IF NOT EXISTS orchestration_approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                reason TEXT DEFAULT '',
                requested_at TEXT DEFAULT (datetime('now')),
                decided_at TEXT,
                decided_by TEXT DEFAULT '',
                FOREIGN KEY (workflow_id) REFERENCES orchestration_workflows(id)
            );

            CREATE INDEX IF NOT EXISTS idx_workflows_status ON orchestration_workflows(status);
            CREATE INDEX IF NOT EXISTS idx_workflows_updated ON orchestration_workflows(updated_at);
            CREATE INDEX IF NOT EXISTS idx_checkpoints_workflow ON workflow_checkpoints(workflow_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_approvals_workflow ON orchestration_approvals(workflow_id, status);
            """
        )


def create_workflow(state: WorkflowState) -> int:
    approval_status = (
        ApprovalStatus.PENDING.value if state.requires_approval else ApprovalStatus.NOT_REQUIRED.value
    )
    state.approval_status = approval_status
    with db.get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO orchestration_workflows
            (workflow_type, goal, status, current_node, assigned_agent, retry_count,
             max_retries, requires_approval, approval_status, state_json, result_json, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                state.workflow_type,
                state.goal,
                state.status,
                state.current_node,
                state.assigned_agent,
                state.retry_count,
                state.max_retries,
                1 if state.requires_approval else 0,
                state.approval_status,
                _json_dump(state.to_dict()),
                _json_dump(state.result),
                state.error,
            ),
        )
        workflow_id = cur.lastrowid
        if state.requires_approval:
            conn.execute(
                "INSERT INTO orchestration_approvals (workflow_id, status) VALUES (?, ?)",
                (workflow_id, ApprovalStatus.PENDING.value),
            )
        return workflow_id


def save_workflow_state(state: WorkflowState) -> None:
    completed_sql = ", completed_at = datetime('now')" if state.status in (
        WorkflowStatus.COMPLETED.value,
        WorkflowStatus.FAILED.value,
        WorkflowStatus.REJECTED.value,
    ) else ""
    with db.get_conn() as conn:
        conn.execute(
            f"""
            UPDATE orchestration_workflows
            SET status = ?, current_node = ?, assigned_agent = ?, retry_count = ?,
                max_retries = ?, requires_approval = ?, approval_status = ?,
                state_json = ?, result_json = ?, error_message = ?,
                updated_at = datetime('now') {completed_sql}
            WHERE id = ?
            """,
            (
                state.status,
                state.current_node,
                state.assigned_agent,
                state.retry_count,
                state.max_retries,
                1 if state.requires_approval else 0,
                state.approval_status,
                _json_dump(state.to_dict()),
                _json_dump(state.result),
                state.error,
                state.workflow_id,
            ),
        )


def load_workflow_state(workflow_id: int) -> Optional[WorkflowState]:
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM orchestration_workflows WHERE id = ?", (workflow_id,)
        ).fetchone()
        if not row:
            return None
        data = _json_load(row["state_json"])
        data.update(
            {
                "workflow_id": row["id"],
                "workflow_type": row["workflow_type"],
                "goal": row["goal"],
                "status": row["status"],
                "current_node": row["current_node"],
                "assigned_agent": row["assigned_agent"],
                "retry_count": row["retry_count"],
                "max_retries": row["max_retries"],
                "requires_approval": bool(row["requires_approval"]),
                "approval_status": row["approval_status"],
                "result": _json_load(row["result_json"]),
                "error": row["error_message"],
            }
        )
        return WorkflowState.from_dict(data)


def list_workflows(status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    with db.get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM orchestration_workflows WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM orchestration_workflows ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]


def checkpoint(state: WorkflowState) -> int:
    with db.get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO workflow_checkpoints (workflow_id, node_name, status, state_json)
            VALUES (?, ?, ?, ?)
            """,
            (state.workflow_id, state.current_node, state.status, _json_dump(state.to_dict())),
        )
        return cur.lastrowid


def latest_checkpoint(workflow_id: int) -> Optional[Dict[str, Any]]:
    with db.get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM workflow_checkpoints
            WHERE workflow_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (workflow_id,),
        ).fetchone()
        return dict(row) if row else None


def log_execution(
    event_type: str,
    detail: str = "",
    workflow_id: Optional[int] = None,
    agent_name: Optional[str] = None,
) -> None:
    with db.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO orchestration_execution_logs
            (workflow_id, agent_name, event_type, detail)
            VALUES (?, ?, ?, ?)
            """,
            (workflow_id, agent_name, event_type, str(detail)[:2000]),
        )


def set_agent_memory(agent_name: str, memory_key: str, memory: Dict[str, Any]) -> None:
    with db.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO orchestration_agent_memory (agent_name, memory_key, memory_json)
            VALUES (?, ?, ?)
            ON CONFLICT(agent_name, memory_key)
            DO UPDATE SET memory_json = excluded.memory_json, updated_at = datetime('now')
            """,
            (agent_name, memory_key, _json_dump(memory)),
        )


def get_agent_memory(agent_name: str, memory_key: str) -> Dict[str, Any]:
    with db.get_conn() as conn:
        row = conn.execute(
            """
            SELECT memory_json FROM orchestration_agent_memory
            WHERE agent_name = ? AND memory_key = ?
            """,
            (agent_name, memory_key),
        ).fetchone()
        return _json_load(row["memory_json"]) if row else {}


def decide_approval(workflow_id: int, approved: bool, decided_by: str = "", reason: str = "") -> None:
    status = ApprovalStatus.APPROVED.value if approved else ApprovalStatus.REJECTED.value
    with db.get_conn() as conn:
        conn.execute(
            """
            UPDATE orchestration_approvals
            SET status = ?, reason = ?, decided_by = ?, decided_at = datetime('now')
            WHERE workflow_id = ? AND status = 'pending'
            """,
            (status, reason, decided_by, workflow_id),
        )
        conn.execute(
            """
            UPDATE orchestration_workflows
            SET approval_status = ?, status = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                status,
                WorkflowStatus.APPROVED.value if approved else WorkflowStatus.REJECTED.value,
                workflow_id,
            ),
        )


def pending_approvals(limit: int = 100) -> List[Dict[str, Any]]:
    with db.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT a.*, w.workflow_type, w.goal, w.assigned_agent
            FROM orchestration_approvals a
            JOIN orchestration_workflows w ON w.id = a.workflow_id
            WHERE a.status = 'pending'
            ORDER BY a.requested_at ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
