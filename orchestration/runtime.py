"""
SentinelAI orchestration runtime.

This is the foundation for persistent AI worker orchestration. It coordinates
LangGraph-style workflow state, CrewAI-compatible worker agents, SQLite
checkpoints, retries, approvals, and recovery without weakening existing safety
systems.
"""

import logging
import threading
from typing import Any, Dict, List, Optional

import db
import queue_manager as qm
from checkpoint_system import SQLiteWorkflowCheckpointer
from graph_runtime import LangGraphRuntimeAdapter
from workflows import create_initial_state

from . import persistence
from .crew_agents import WorkerAgentRegistry
from .models import ApprovalStatus, WorkflowState, WorkflowStatus

logger = logging.getLogger(__name__)


class SentinelOrchestrator:
    """Persistent orchestration controller for SentinelAI workflows."""

    def __init__(self):
        self.lock = threading.RLock()
        self.agents = WorkerAgentRegistry()
        self.checkpointer = SQLiteWorkflowCheckpointer()
        self.graph = LangGraphRuntimeAdapter(
            {
                "route_task": self._route_task,
                "approval_checkpoint": self._approval_checkpoint,
                "execute_agent": self._execute_agent,
                "persist_result": self._persist_result,
            }
        )

    def initialize(self) -> None:
        persistence.init_orchestration_tables()
        persistence.log_execution(
            "orchestration_initialized",
            f"langgraph_available={self.graph.langgraph_available}",
        )
        db.log_event("orchestration_initialized", "Sentinel orchestration runtime initialized")

    def submit_workflow(
        self,
        goal: str,
        workflow_type: str = "general",
        requires_approval: bool = True,
        max_retries: int = 3,
        enqueue: bool = True,
    ) -> Dict[str, Any]:
        if not goal or not goal.strip():
            raise ValueError("goal is required")

        with self.lock:
            state = create_initial_state(
                goal=goal.strip(),
                workflow_type=workflow_type,
                requires_approval=requires_approval,
                max_retries=max_retries,
            )
            state.add_event("workflow_submitted", {"workflow_type": workflow_type})
            workflow_id = persistence.create_workflow(state)
            state.workflow_id = workflow_id
            self._save(state)

            queue_task_id = None
            if enqueue:
                queue_task_id = qm.enqueue_task(
                    "orchestration_workflow",
                    priority=3,
                    task_data={"workflow_id": workflow_id},
                    max_retries=max_retries,
                )
                persistence.log_execution(
                    "workflow_enqueued",
                    f"queue_task_id={queue_task_id}",
                    workflow_id=workflow_id,
                )

            return {
                "workflow_id": workflow_id,
                "queue_task_id": queue_task_id,
                "status": state.status,
                "approval_status": state.approval_status,
            }

    def run_workflow(self, workflow_id: int) -> Dict[str, Any]:
        with self.lock:
            state = persistence.load_workflow_state(workflow_id)
            if not state:
                raise ValueError(f"Workflow {workflow_id} not found")
            if state.status in (WorkflowStatus.COMPLETED.value, WorkflowStatus.REJECTED.value):
                return state.to_dict()

            state.status = WorkflowStatus.RUNNING.value
            state.add_event("workflow_run_started", {"node": state.current_node})
            self._save(state)

            try:
                state = self.graph.run(state)
            except Exception as exc:
                logger.exception("Workflow %s execution failed", workflow_id)
                state.error = str(exc)
                state.retry_count += 1
                if state.retry_count <= state.max_retries:
                    state.status = WorkflowStatus.PENDING.value
                    state.current_node = "retry_scheduled"
                else:
                    state.status = WorkflowStatus.FAILED.value
                    state.current_node = "failed"
                state.add_event(
                    "workflow_error",
                    {"error": state.error, "retry_count": state.retry_count},
                )
                self._save(state)

            return state.to_dict()

    def approve_workflow(self, workflow_id: int, decided_by: str = "user", reason: str = "") -> Dict[str, Any]:
        with self.lock:
            persistence.decide_approval(workflow_id, approved=True, decided_by=decided_by, reason=reason)
            state = persistence.load_workflow_state(workflow_id)
            if not state:
                raise ValueError(f"Workflow {workflow_id} not found")
            state.approval_status = ApprovalStatus.APPROVED.value
            state.status = WorkflowStatus.APPROVED.value
            state.add_event("workflow_approved", {"decided_by": decided_by, "reason": reason})
            self._save(state)
            return state.to_dict()

    def reject_workflow(self, workflow_id: int, decided_by: str = "user", reason: str = "") -> Dict[str, Any]:
        with self.lock:
            persistence.decide_approval(workflow_id, approved=False, decided_by=decided_by, reason=reason)
            state = persistence.load_workflow_state(workflow_id)
            if not state:
                raise ValueError(f"Workflow {workflow_id} not found")
            state.approval_status = ApprovalStatus.REJECTED.value
            state.status = WorkflowStatus.REJECTED.value
            state.current_node = "rejected"
            state.add_event("workflow_rejected", {"decided_by": decided_by, "reason": reason})
            self._save(state)
            return state.to_dict()

    def recover_workflows(self) -> int:
        """Reset interrupted running workflows to pending for replay."""
        recovered = 0
        for row in persistence.list_workflows(limit=500):
            if row["status"] == WorkflowStatus.RUNNING.value:
                state = persistence.load_workflow_state(row["id"])
                if not state:
                    continue
                state.status = WorkflowStatus.RECOVERED.value
                state.current_node = "recovered_from_crash"
                state.add_event("workflow_recovered", {"previous_status": row["status"]})
                self._save(state)
                qm.enqueue_task(
                    "orchestration_workflow",
                    priority=2,
                    task_data={"workflow_id": state.workflow_id, "recovered": True},
                    max_retries=state.max_retries,
                )
                recovered += 1
        if recovered:
            persistence.log_execution("workflow_recovery", f"Recovered {recovered} workflows")
            db.log_event("orchestration_recovery", f"Recovered {recovered} workflows")
        return recovered

    def handle_queue_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        task_data = task.get("task_data") or {}
        workflow_id = task_data.get("workflow_id")
        if not workflow_id:
            raise ValueError("orchestration_workflow task missing workflow_id")
        return self.run_workflow(int(workflow_id))

    def list_workflows(self, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        return persistence.list_workflows(status=status, limit=limit)

    def get_workflow(self, workflow_id: int) -> Optional[Dict[str, Any]]:
        state = persistence.load_workflow_state(workflow_id)
        return state.to_dict() if state else None

    def pending_approvals(self, limit: int = 100) -> List[Dict[str, Any]]:
        return persistence.pending_approvals(limit)

    def status(self) -> Dict[str, Any]:
        workflows = persistence.list_workflows(limit=500)
        counts: Dict[str, int] = {}
        for row in workflows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        return {
            "initialized": True,
            "langgraph_available": self.graph.langgraph_available,
            "crewai_available": any(a["crewai_available"] for a in self.agents.list_agents().values()),
            "workflow_counts": counts,
            "agents": self.agents.list_agents(),
            "pending_approvals": len(self.pending_approvals(limit=500)),
        }

    def _route_task(self, state: WorkflowState) -> WorkflowState:
        agent = self.agents.choose_agent(state.workflow_type, state.goal)
        state.assigned_agent = agent.name
        state.current_node = "route_task"
        state.add_event("task_routed", {"agent": agent.name})
        self._save(state)
        return state

    def _approval_checkpoint(self, state: WorkflowState) -> WorkflowState:
        state.current_node = "approval_checkpoint"
        if not state.requires_approval:
            state.approval_status = ApprovalStatus.NOT_REQUIRED.value
            state.add_event("approval_skipped", {"reason": "not_required"})
        elif state.approval_status == ApprovalStatus.APPROVED.value:
            state.add_event("approval_confirmed", {})
        elif state.approval_status == ApprovalStatus.REJECTED.value:
            state.status = WorkflowStatus.REJECTED.value
            state.add_event("approval_rejected", {})
        else:
            state.status = WorkflowStatus.AWAITING_APPROVAL.value
            state.approval_status = ApprovalStatus.PENDING.value
            state.add_event("approval_waiting", {"message": "Human approval required"})
        self._save(state)
        return state

    def _execute_agent(self, state: WorkflowState) -> WorkflowState:
        state.current_node = "execute_agent"
        state.status = WorkflowStatus.RUNNING.value
        agent = self.agents.choose_agent(state.workflow_type, state.goal)
        state.assigned_agent = agent.name
        result = agent.execute(state.to_dict())
        if not result.success:
            state.error = result.error
            state.retry_count += 1
            state.status = WorkflowStatus.PENDING.value if state.retry_count <= state.max_retries else WorkflowStatus.FAILED.value
        else:
            state.result = result.output
            state.status = WorkflowStatus.RUNNING.value
            state.add_event("agent_completed", {"agent": result.agent_name})
        self._save(state)
        return state

    def _persist_result(self, state: WorkflowState) -> WorkflowState:
        state.current_node = "persist_result"
        if state.status != WorkflowStatus.FAILED.value:
            state.status = WorkflowStatus.COMPLETED.value
        state.add_event("workflow_result_persisted", {"status": state.status})
        self._save(state)
        return state

    def _save(self, state: WorkflowState) -> None:
        if state.workflow_id is not None:
            persistence.save_workflow_state(state)
            self.checkpointer.save(state)


_orchestrator: Optional[SentinelOrchestrator] = None


def get_orchestrator() -> SentinelOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = SentinelOrchestrator()
    return _orchestrator


def initialize_orchestration() -> SentinelOrchestrator:
    orchestrator = get_orchestrator()
    orchestrator.initialize()
    return orchestrator
