"""Workflow recovery and continuation planning."""

from typing import Dict


class WorkflowRecoveryPlanner:
    def plan(self, workflow_state: Dict) -> Dict:
        return {
            "workflow_id": workflow_state.get("workflow_id"),
            "resume_from": workflow_state.get("current_node", "created"),
            "retry_count": workflow_state.get("retry_count", 0),
            "recommended_action": "resume_from_checkpoint",
        }
