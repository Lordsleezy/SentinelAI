"""
Shared orchestration models for SentinelAI.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class WorkflowStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    RECOVERED = "recovered"


class ApprovalStatus(Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AgentRole(Enum):
    PLANNER = "PlannerAgent"
    RESEARCH = "ResearchAgent"
    CODING = "CodingAgent"
    DEBUGGING = "DebuggingAgent"
    UI = "UIAgent"
    MONITORING = "MonitoringAgent"
    DEPLOYMENT = "DeploymentAgent"
    REVENUE_DISCOVERY = "RevenueDiscoveryAgent"
    REFLECTION = "ReflectionAgent"
    MEMORY = "MemoryAgent"
    FILESYSTEM = "FilesystemAgent"
    RESEARCH_COORDINATOR = "ResearchCoordinatorAgent"


@dataclass
class WorkflowState:
    workflow_id: Optional[int]
    workflow_type: str
    goal: str
    status: str = WorkflowStatus.PENDING.value
    current_node: str = "created"
    assigned_agent: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    approval_status: str = ApprovalStatus.NOT_REQUIRED.value
    requires_approval: bool = True
    result: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    memory: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "workflow_type": self.workflow_type,
            "goal": self.goal,
            "status": self.status,
            "current_node": self.current_node,
            "assigned_agent": self.assigned_agent,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "approval_status": self.approval_status,
            "requires_approval": self.requires_approval,
            "result": self.result,
            "error": self.error,
            "memory": self.memory,
            "events": self.events,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowState":
        return cls(
            workflow_id=data.get("workflow_id"),
            workflow_type=data.get("workflow_type", "general"),
            goal=data.get("goal", ""),
            status=data.get("status", WorkflowStatus.PENDING.value),
            current_node=data.get("current_node", "created"),
            assigned_agent=data.get("assigned_agent"),
            retry_count=int(data.get("retry_count", 0)),
            max_retries=int(data.get("max_retries", 3)),
            approval_status=data.get("approval_status", ApprovalStatus.NOT_REQUIRED.value),
            requires_approval=bool(data.get("requires_approval", True)),
            result=data.get("result") or {},
            error=data.get("error"),
            memory=data.get("memory") or {},
            events=data.get("events") or [],
        )

    def add_event(self, event_type: str, detail: Dict[str, Any]) -> None:
        self.events.append(
            {
                "type": event_type,
                "detail": detail,
                "timestamp": datetime.utcnow().isoformat(timespec="seconds"),
            }
        )
