"""Failure analysis for orchestration retries."""

from typing import Dict


class FailureAnalyzer:
    def analyze(self, workflow_state: Dict) -> Dict:
        error = workflow_state.get("error") or ""
        if not error:
            return {"failure_type": "none", "retry_recommended": False, "reason": "no error"}
        lowered = error.lower()
        if any(term in lowered for term in ("timeout", "rate", "temporar", "connection")):
            return {"failure_type": "transient", "retry_recommended": True, "reason": error[:300]}
        if any(term in lowered for term in ("unauthorized", "forbidden", "approval", "credential")):
            return {"failure_type": "safety_or_auth", "retry_recommended": False, "reason": error[:300]}
        return {"failure_type": "unknown", "retry_recommended": workflow_state.get("retry_count", 0) < workflow_state.get("max_retries", 3), "reason": error[:300]}
