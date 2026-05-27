"""
LangGraph-compatible SQLite checkpoint facade for SentinelAI.
"""

from typing import Any, Dict, Optional

from orchestration.models import WorkflowState
from orchestration import persistence


class SQLiteWorkflowCheckpointer:
    """Checkpoint workflow state into SentinelAI's SQLite database."""

    def save(self, state: WorkflowState) -> int:
        return persistence.checkpoint(state)

    def load_latest(self, workflow_id: int) -> Optional[Dict[str, Any]]:
        return persistence.latest_checkpoint(workflow_id)
