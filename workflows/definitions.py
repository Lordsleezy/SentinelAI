"""
Reusable workflow definitions for SentinelAI.
"""

from orchestration.models import ApprovalStatus, WorkflowState


DEFAULT_WORKFLOW_TYPES = {
    "general": "General supervised task workflow",
    "research": "Research and analysis workflow",
    "coding": "Code implementation workflow",
    "debugging": "Failure diagnosis workflow",
    "ui": "User interface workflow",
    "monitoring": "Operational monitoring workflow",
    "deployment": "Deployment workflow",
    "revenue_discovery": "Revenue discovery workflow",
}


def create_initial_state(
    goal: str,
    workflow_type: str = "general",
    requires_approval: bool = True,
    max_retries: int = 3,
) -> WorkflowState:
    return WorkflowState(
        workflow_id=None,
        workflow_type=workflow_type if workflow_type in DEFAULT_WORKFLOW_TYPES else "general",
        goal=goal,
        requires_approval=requires_approval,
        max_retries=max_retries,
        approval_status=ApprovalStatus.PENDING.value if requires_approval else ApprovalStatus.NOT_REQUIRED.value,
    )
