"""First launch wizard state — Welcome → Scan → Deps → Models → License → Ready."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from core.onboarding.debug_logger import StepWatchdog

logger = logging.getLogger("sentinel.onboarding")

_ROOT = Path(__file__).resolve().parents[2]
_STATE_PATH = _ROOT / "data" / "onboarding" / "first_launch.json"

STEPS = (
    "welcome",
    "system_scan",
    "dependencies",
    "models",
    "model_validation",
    "account",
    "license",
    "ready",
)


class FirstLaunchOrchestrator:
    def __init__(self) -> None:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load()

    def _load(self) -> Dict[str, Any]:
        if _STATE_PATH.is_file():
            try:
                return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "completed": False,
            "current_step": "welcome",
            "errors": [],
            "progress_percent": 0,
            "steps_done": [],
        }

    def _save(self) -> None:
        _STATE_PATH.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    def status(self) -> Dict[str, Any]:
        return dict(self._state)

    def is_complete(self) -> bool:
        return bool(self._state.get("completed"))

    def mark_completed(
        self,
        *,
        allow_degraded: bool = True,
        components: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._state["completed"] = True
        self._state["allow_degraded"] = allow_degraded
        self._state["progress_percent"] = 100
        self._state["current_step"] = "ready"
        if components:
            self._state["components"] = components
        if "ready" not in self._state.get("steps_done", []):
            self._state.setdefault("steps_done", []).append("ready")
        self._save()

    def run_step(self, step: Optional[str] = None) -> Dict[str, Any]:
        step = step or self._state.get("current_step", "welcome")
        if step not in STEPS:
            return {"ok": False, "error": f"invalid step: {step}"}
        self._state["current_step"] = step
        result: Dict[str, Any] = {"step": step, "ok": True}

        try:
            with StepWatchdog(f"first_launch.{step}"):
                if step == "welcome":
                    result["message"] = "Welcome to Sentinel AI"
                    self._advance(step, 5)
                elif step == "system_scan":
                    from core.onboarding.pipeline import get_onboarding_pipeline
                    pipe = get_onboarding_pipeline()
                    profile = pipe.run_fast_scan()
                    pipe.start_background_setup(profile)
                    result["profile"] = profile
                    result["progress"] = pipe.progress()
                    self._advance(step, 20)
                elif step == "dependencies":
                    from core.onboarding.pipeline import get_onboarding_pipeline
                    result["message"] = "Dependencies installing in background"
                    result["progress"] = get_onboarding_pipeline().progress()
                    self._advance(step, 45)
                elif step == "models":
                    from core.onboarding.pipeline import get_onboarding_pipeline
                    result["message"] = "Models installing in background"
                    result["progress"] = get_onboarding_pipeline().progress()
                    self._advance(step, 70)
                elif step == "model_validation":
                    from core.model_runtime import get_model_runtime
                    result["readiness"] = get_model_runtime().readiness_quick()
                    result["message"] = "Validation runs in background; chat is available"
                    self._advance(step, 90)
                elif step == "account":
                    result["message"] = "Optional: configure integrations in Settings"
                    self._advance(step, 85)
                elif step == "license":
                    try:
                        from workers.licensing.license_manager import get_license_manager
                        lm = get_license_manager()
                        lm.start_beta_period()
                        result["license"] = lm.get_status()
                    except Exception as lic_err:
                        result["license"] = {"tier": "free", "skipped": str(lic_err)[:120]}
                    self._advance(step, 95)
                elif step == "ready":
                    self.mark_completed(allow_degraded=True)
        except Exception as e:
            logger.exception("first launch step %s", step)
            self._record_error(str(e))
            result = {"ok": True, "step": step, "error": str(e), "continued": True}
            if step == "ready":
                self.mark_completed(allow_degraded=True)

        self._save()
        result["status"] = self.status()
        return result

    def run_all(self) -> Dict[str, Any]:
        for step in STEPS:
            self.run_step(step)
        return {"ok": True, "status": self.status()}

    def retry_step(self, step: str) -> Dict[str, Any]:
        self._state["errors"] = [e for e in self._state.get("errors", []) if e.get("step") != step]
        self._state["current_step"] = step
        return self.run_step(step)

    def _advance(self, step: str, progress: int) -> None:
        if step not in self._state.get("steps_done", []):
            self._state.setdefault("steps_done", []).append(step)
        self._state["progress_percent"] = max(self._state.get("progress_percent", 0), progress)
        idx = STEPS.index(step)
        if idx + 1 < len(STEPS):
            self._state["current_step"] = STEPS[idx + 1]

    def _record_error(self, message: str) -> None:
        self._state.setdefault("errors", []).append({
            "step": self._state.get("current_step"),
            "message": message,
            "at": datetime.now(timezone.utc).isoformat(),
        })


_orchestrator: Optional[FirstLaunchOrchestrator] = None


def get_first_launch() -> FirstLaunchOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = FirstLaunchOrchestrator()
    return _orchestrator
