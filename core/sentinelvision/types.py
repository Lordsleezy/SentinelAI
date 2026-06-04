"""SentinelScrub shared types."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class GoalStatus(str, Enum):
    QUEUED = "queued"
    RESEARCHING = "researching"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    REPAIRING = "repairing"
    COMPLETED = "completed"
    FAILED = "failed"
    AWAITING_APPROVAL = "awaiting_approval"


SENSITIVE_ACTION_TYPES = frozenset({
    "purchase",
    "payment",
    "account_create",
    "subscription",
    "credential_change",
    "financial",
})


@dataclass
class Goal:
    goal_id: str
    objective: str
    status: GoalStatus
    created_at: str
    completed_at: Optional[str] = None
    provider_id: Optional[str] = None
    plan_id: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "objective": self.objective,
            "status": self.status.value if isinstance(self.status, GoalStatus) else self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "provider_id": self.provider_id,
            "plan_id": self.plan_id,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class PlanStep:
    step_id: str
    action_type: str
    description: str
    params: Dict[str, Any] = field(default_factory=dict)
    requires_approval: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "action_type": self.action_type,
            "description": self.description,
            "params": self.params,
            "requires_approval": self.requires_approval,
        }


@dataclass
class ExecutionPlan:
    plan_id: str
    goal_id: str
    steps: List[PlanStep]
    provider_id: str
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "goal_id": self.goal_id,
            "steps": [s.to_dict() for s in self.steps],
            "provider_id": self.provider_id,
            "created_at": self.created_at,
        }


@dataclass
class ApprovalRequest:
    approval_id: str
    goal_id: str
    action: str
    cost: Optional[str]
    account: Optional[str]
    expected_result: str
    provider_id: str
    created_at: str
    status: str = "pending"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "goal_id": self.goal_id,
            "action": self.action,
            "cost": self.cost,
            "account": self.account,
            "expected_result": self.expected_result,
            "provider_id": self.provider_id,
            "created_at": self.created_at,
            "status": self.status,
            "metadata": self.metadata,
        }


@dataclass
class FeedEvent:
    goal_id: str
    phase: str
    message: str
    timestamp: str
    level: str = "info"
    artifact_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "phase": self.phase,
            "message": self.message,
            "timestamp": self.timestamp,
            "level": self.level,
            "artifact_path": self.artifact_path,
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
