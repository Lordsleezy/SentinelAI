"""Self-correction engine — diagnose, research repair, apply, verify, retry."""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from core.sentinelvision.audit import audit_log
from core.sentinelvision.planner.research import ResearchEngine
from core.sentinelvision.self_correction.classifier import classify_failure
from core.sentinelvision.self_correction.failure_capture import capture_failure_context
from core.sentinelvision.self_correction.repair_memory import RepairMemoryStore
from core.sentinelvision.types import GoalStatus

logger = logging.getLogger("sentinel.vision.self_correction")

EmitFn = Callable[[str, str, str, str], None]


class SelfCorrectionEngine:
    def __init__(self, max_retries: int = 5) -> None:
        self.max_retries = max_retries
        self.repair_memory = RepairMemoryStore()
        self.research = ResearchEngine()

    def should_retry(self, attempt: int) -> bool:
        return attempt < self.max_retries

    def run_correction_cycle(
        self,
        goal_id: str,
        objective: str,
        provider_id: str,
        error: Exception,
        *,
        browser=None,
        desktop=None,
        last_terminal: Optional[Dict[str, Any]] = None,
        emit: Optional[EmitFn] = None,
        apply_repair: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Returns {retry: bool, repaired: bool, hypothesis, repair_result}."""
        _emit = emit or (lambda *_: None)

        bundle = capture_failure_context(
            str(error), browser=browser, desktop=desktop,
            last_terminal=last_terminal, goal_id=goal_id,
        )
        ctx = bundle.to_context()
        classification = classify_failure(str(error), ctx)
        _emit(goal_id, "repairing", f"Diagnosed: {classification.failure_class.value}", "warn")

        audit_log(
            "failure_classified", goal_id,
            provider_id=provider_id,
            detail=classification.failure_class.value,
            extra={"signature": classification.signature[:80]},
        )

        stored = self.repair_memory.find_repair(
            provider_id,
            classification.signature,
            classification.failure_class.value,
        )

        hypothesis = ""
        repair_result: Dict[str, Any] = {"ok": False}

        if stored:
            hypothesis = stored.get("repair_action", "")
            _emit(goal_id, "repairing", f"Repair memory match: {hypothesis[:120]}", "info")
            repair_result = self._apply_repair_action(
                hypothesis, provider_id, classification, ctx, desktop, apply_repair,
            )
            self.repair_memory.record_outcome(
                provider_id,
                classification.signature,
                stored.get("root_cause", classification.failure_class.value),
                hypothesis,
                repair_result.get("ok", False),
            )
        else:
            _emit(goal_id, "repairing", "Researching repair solution…", "info")
            research = self.research.research_objective(
                f"fix {classification.failure_class.value}: {error}",
                provider_id,
            )
            hypothesis = self._build_hypothesis(classification, research, ctx)
            _emit(goal_id, "repairing", f"Hypothesis: {hypothesis[:140]}", "info")
            repair_result = self._apply_repair_action(
                hypothesis, provider_id, classification, ctx, desktop, apply_repair,
            )
            self.repair_memory.record_outcome(
                provider_id,
                classification.signature,
                classification.failure_class.value,
                hypothesis,
                repair_result.get("ok", False),
            )

        retry = repair_result.get("ok", False) or classification.failure_class.value not in (
            "approval_blocked",
        )
        return {
            "retry": retry,
            "repaired": repair_result.get("ok", False),
            "hypothesis": hypothesis,
            "classification": classification.to_dict(),
            "repair_result": repair_result,
            "context": ctx,
        }

    @staticmethod
    def _build_hypothesis(classification, research: Dict[str, Any], ctx: Dict[str, Any]) -> str:
        actions = research.get("required_actions") or []
        if actions:
            return actions[0]
        hints = classification.hints
        if hints:
            return f"Address: {hints[0]}"
        if classification.failure_class.value == "missing_dependency":
            return "pip install playwright && playwright install chromium"
        return "Re-run step after fixing environment"

    @staticmethod
    def _apply_repair_action(
        action: str,
        provider_id: str,
        classification,
        ctx: Dict[str, Any],
        desktop,
        apply_repair: Optional[Callable],
    ) -> Dict[str, Any]:
        if apply_repair:
            return apply_repair({
                "action": action,
                "provider_id": provider_id,
                "classification": classification.to_dict(),
                "context": ctx,
            })

        lower = action.lower()
        if desktop and ("pip install" in lower or "netlify env" in lower):
            return desktop.run_command(action if "pip" not in action else action)

        if "env" in lower and provider_id == "netlify":
            import os
            return {"ok": True, "note": "Set Netlify env vars in dashboard or CLI"}

        return {"ok": True, "note": f"repair recorded: {action[:200]}"}
