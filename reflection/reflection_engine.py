"""Execution reflection and self-critique."""

from typing import Dict

import db
from execution_analysis import FailureAnalyzer
from memory.persistent_memory import get_memory
from scoring import ExecutionScorer


class ReflectionEngine:
    def __init__(self):
        self.scorer = ExecutionScorer()
        self.failure_analyzer = FailureAnalyzer()

    def reflect(self, workflow_state: Dict) -> Dict:
        score = self.scorer.score(workflow_state)
        failure = self.failure_analyzer.analyze(workflow_state)
        reflection = {
            "workflow_id": workflow_state.get("workflow_id"),
            "score": score,
            "failure": failure,
            "improvements": self._improvements(workflow_state, failure),
        }
        get_memory().remember_execution(
            f"Workflow {workflow_state.get('workflow_id')} reflection: {reflection}",
            {"workflow_id": workflow_state.get("workflow_id"), "status": workflow_state.get("status")},
        )
        db.log_event("workflow_reflected", f"{workflow_state.get('workflow_id')} score={score['score']}")
        return reflection

    def _improvements(self, workflow_state: Dict, failure: Dict) -> list:
        improvements = []
        if failure.get("retry_recommended"):
            improvements.append("Retry with recovered checkpoint context.")
        if workflow_state.get("approval_status") == "pending":
            improvements.append("Wait for human approval before execution.")
        if not workflow_state.get("result"):
            improvements.append("Persist a structured result before completion.")
        return improvements or ["No immediate improvement required."]
