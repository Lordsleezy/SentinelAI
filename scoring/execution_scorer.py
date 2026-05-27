"""Simple execution scoring for workflow reflection."""

from typing import Dict


class ExecutionScorer:
    def score(self, workflow_state: Dict) -> Dict:
        score = 1.0
        reasons = []
        if workflow_state.get("status") == "completed":
            score += 4.0
            reasons.append("completed")
        if workflow_state.get("error"):
            score -= 2.0
            reasons.append("error_present")
        retries = int(workflow_state.get("retry_count", 0))
        if retries:
            score -= min(retries, 3) * 0.5
            reasons.append(f"retries={retries}")
        if workflow_state.get("result"):
            score += 1.0
            reasons.append("result_persisted")
        final = max(0.0, min(5.0, score))
        return {"score": final, "reasons": reasons}
