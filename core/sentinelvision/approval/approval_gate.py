"""Approval gate for sensitive SentinelScrub actions."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from typing import Any, Dict, List, Optional

from core.sentinelvision.audit import audit_log
from core.sentinelvision.goal_engine import GoalEngine, _connect, _lock
from core.sentinelvision.types import ApprovalRequest, GoalStatus, SENSITIVE_ACTION_TYPES, utc_now

_trusted_providers: Dict[str, bool] = {}


class ApprovalGate:
    def __init__(self, goals: GoalEngine) -> None:
        self.goals = goals

    def requires_approval(self, action_type: str) -> bool:
        return (action_type or "").lower() in SENSITIVE_ACTION_TYPES

    def create_request(
        self,
        goal_id: str,
        *,
        action: str,
        expected_result: str,
        provider_id: str,
        cost: Optional[str] = None,
        account: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ApprovalRequest:
        if _trusted_providers.get(provider_id) and action not in ("credential_change",):
            audit_log("approval_auto_trusted", goal_id, provider_id=provider_id, action=action)
            req = ApprovalRequest(
                approval_id=str(uuid.uuid4()),
                goal_id=goal_id,
                action=action,
                cost=cost,
                account=account,
                expected_result=expected_result,
                provider_id=provider_id,
                created_at=utc_now(),
                status="approved",
                metadata=metadata or {},
            )
            self._persist(req)
            return req

        req = ApprovalRequest(
            approval_id=str(uuid.uuid4()),
            goal_id=goal_id,
            action=action,
            cost=cost,
            account=account,
            expected_result=expected_result,
            provider_id=provider_id,
            created_at=utc_now(),
            status="pending",
            metadata=metadata or {},
        )
        self._persist(req)
        self.goals.set_status(goal_id, GoalStatus.AWAITING_APPROVAL)
        self.goals.append_feed(goal_id, "approval", f"Approval required: {action}", level="warn")
        audit_log("approval_requested", goal_id, provider_id=provider_id, action=action)
        return req

    def resolve(self, approval_id: str, approved: bool) -> Optional[ApprovalRequest]:
        req = self.get(approval_id)
        if not req or req.status != "pending":
            return None
        req.status = "approved" if approved else "rejected"
        self._persist(req)
        audit_log("approval_resolved", req.goal_id, action=req.action, detail=req.status)
        if approved:
            self.goals.set_status(req.goal_id, GoalStatus.EXECUTING)
            self.goals.append_feed(req.goal_id, "approval", "Approved — continuing execution")
        else:
            self.goals.set_status(req.goal_id, GoalStatus.FAILED, error="User rejected approval")
            self.goals.append_feed(req.goal_id, "approval", "Rejected by user", level="error")
        return req

    def set_trusted_provider(self, provider_id: str, trusted: bool) -> None:
        _trusted_providers[provider_id] = trusted
        audit_log("provider_trust", provider_id=provider_id, detail=str(trusted))

    def list_pending(self, goal_id: Optional[str] = None) -> List[ApprovalRequest]:
        with _lock:
            conn = _connect()
            try:
                if goal_id:
                    rows = conn.execute(
                        "SELECT * FROM approvals WHERE goal_id = ? AND status = 'pending'",
                        (goal_id,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM approvals WHERE status = 'pending' ORDER BY created_at DESC"
                    ).fetchall()
            finally:
                conn.close()
        return [self._row_to_req(r) for r in rows]

    def get(self, approval_id: str) -> Optional[ApprovalRequest]:
        with _lock:
            conn = _connect()
            try:
                row = conn.execute(
                    "SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)
                ).fetchone()
            finally:
                conn.close()
        return self._row_to_req(row) if row else None

    def _persist(self, req: ApprovalRequest) -> None:
        with _lock:
            conn = _connect()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO approvals (approval_id, goal_id, payload, status, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        req.approval_id,
                        req.goal_id,
                        json.dumps(req.to_dict()),
                        req.status,
                        req.created_at,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    @staticmethod
    def _row_to_req(row: sqlite3.Row) -> ApprovalRequest:
        payload = json.loads(row["payload"])
        return ApprovalRequest(
            approval_id=payload["approval_id"],
            goal_id=payload["goal_id"],
            action=payload["action"],
            cost=payload.get("cost"),
            account=payload.get("account"),
            expected_result=payload["expected_result"],
            provider_id=payload["provider_id"],
            created_at=payload["created_at"],
            status=row["status"],
            metadata=payload.get("metadata") or {},
        )
