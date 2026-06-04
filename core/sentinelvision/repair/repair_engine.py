"""Self-repair — analyze failure, replan, retry with limits."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.sentinelvision.audit import audit_log
from core.sentinelvision.providers.registry import get_provider

logger = logging.getLogger("sentinel.vision.repair")


class RepairEngine:
    def __init__(self, max_retries: int = 3) -> None:
        self.max_retries = max_retries

    def analyze_failure(self, goal_id: str, error: str, context: Dict[str, Any]) -> Dict[str, Any]:
        causes = []
        lower = (error or "").lower()
        if "playwright" in lower:
            causes.append("Install Playwright: pip install playwright && playwright install chromium")
        if "approval" in lower or "rejected" in lower:
            causes.append("User approval required or was rejected")
        if "credential" in lower or "vault" in lower:
            causes.append("Register provider credentials in Sentinel Vision vault")
        if not causes:
            causes.append("Review execution logs and provider documentation")
        return {"goal_id": goal_id, "error": error, "likely_causes": causes, "context_keys": list(context.keys())}

    def build_repair_plan(
        self,
        goal_id: str,
        provider_id: str,
        failure: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        provider = get_provider(provider_id)
        if provider:
            repair = provider.repair(failure, failure.get("context") or {})
            plan = repair.get("repair_plan") or []
            if plan:
                return plan
        analysis = self.analyze_failure(goal_id, failure.get("error", ""), failure.get("context") or {})
        steps = []
        for i, cause in enumerate(analysis.get("likely_causes") or [], 1):
            steps.append({"step_id": f"r{i}", "action_type": "repair", "description": cause})
        return steps

    def should_retry(self, attempt: int) -> bool:
        return attempt < self.max_retries

    def log_repair_attempt(self, goal_id: str, attempt: int, detail: str) -> None:
        audit_log("repair_attempt", goal_id, detail=f"attempt={attempt}: {detail[:300]}")
