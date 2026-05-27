"""Runtime workflow state transitions."""

from orchestration.models import WorkflowState


class WorkflowStateMachine:
    def transition(self, state: WorkflowState, node: str, status: str = None) -> WorkflowState:
        state.current_node = node
        if status:
            state.status = status
        state.add_event("state_transition", {"node": node, "status": state.status})
        return state
