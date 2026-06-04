"""Background onboarding pipeline — never blocks UI; always allows chat."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.onboarding.debug_logger import StepWatchdog, log_event

_ROOT = Path(__file__).resolve().parents[2]
_PROGRESS_PATH = _ROOT / "data" / "onboarding" / "pipeline_progress.json"
_LOCK = threading.RLock()
_bg_started = False


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_progress() -> Dict[str, Any]:
    return {
        "current_step": "idle",
        "percent": 0,
        "message": "Waiting to start…",
        "components": {},
        "errors": [],
        "background_running": False,
        "allow_chat": True,
        "completed": False,
        "updated_at": _utc(),
    }


class OnboardingPipeline:
    def __init__(self) -> None:
        _PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load()
        # Recover from crashed background worker leaving background_running=true
        if self._state.get("background_running") and not self._state.get("completed"):
            self._state["background_running"] = False
            self._save()

    def _load(self) -> Dict[str, Any]:
        if _PROGRESS_PATH.is_file():
            try:
                return json.loads(_PROGRESS_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return _default_progress()

    def _save(self) -> None:
        self._state["updated_at"] = _utc()
        _PROGRESS_PATH.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    def progress(self) -> Dict[str, Any]:
        with _LOCK:
            return dict(self._state)

    def _set_step(self, step: str, percent: int, message: str) -> None:
        with _LOCK:
            self._state["current_step"] = step
            self._state["percent"] = percent
            self._state["message"] = message
            self._save()
        log_event(step, phase="progress", detail={"percent": percent, "message": message})

    def _mark_component(self, cid: str, status: str, message: str = "") -> None:
        with _LOCK:
            self._state.setdefault("components", {})[cid] = {
                "status": status,
                "message": message,
                "at": _utc(),
            }
            if status in ("failed", "needs_repair"):
                self._state.setdefault("errors", []).append({"component": cid, "message": message, "at": _utc()})
            self._save()

    def run_fast_scan(self) -> Dict[str, Any]:
        with StepWatchdog("pipeline_fast_scan"):
            from core.onboarding.hardware_probe import probe_machine_profile
            profile = probe_machine_profile()
            self._set_step("system_scan", 15, "Hardware scan complete")
            return profile

    def start_background_setup(self, profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        global _bg_started
        with _LOCK:
            if self._state.get("background_running"):
                return {"ok": True, "skipped": True, "progress": dict(self._state)}
            self._state["background_running"] = True
            self._state["allow_chat"] = True
            self._save()
            _bg_started = True

        def _worker() -> None:
            try:
                self._background_worker(profile or {})
            finally:
                with _LOCK:
                    self._state["background_running"] = False
                    self._save()

        threading.Thread(target=_worker, name="onboarding-bg", daemon=True).start()
        log_event("background_setup", phase="started")
        return {"ok": True, "progress": self.progress()}

    def _background_worker(self, profile: Dict[str, Any]) -> None:
        import os
        simulate_no_ollama = os.environ.get("SENTINEL_SIMULATE_NO_OLLAMA") == "1"
        simulate_offline = os.environ.get("SENTINEL_SIMULATE_OFFLINE") == "1"

        with StepWatchdog("background_setup_total"):
            # Ollama
            self._set_step("ollama", 25, "Checking local AI runtime…")
            try:
                from core.model_runtime import get_model_runtime
                rt = get_model_runtime()
                if simulate_no_ollama or simulate_offline:
                    self._mark_component("ollama", "needs_repair", "Simulated: Ollama unavailable")
                elif not rt.ollama_installed():
                    with StepWatchdog("bg_install_ollama"):
                        res = rt.install_ollama()
                    if res.get("ok"):
                        self._mark_component("ollama", "installed")
                    else:
                        self._mark_component("ollama", "needs_repair", res.get("user_message", "Ollama not installed"))
                elif not rt.ollama_running():
                    with StepWatchdog("bg_start_ollama"):
                        res = rt.ensure_ollama_running()
                    self._mark_component(
                        "ollama",
                        "installed" if res.get("ok") else "needs_repair",
                        res.get("user_message", ""),
                    )
                else:
                    self._mark_component("ollama", "installed")
            except Exception as e:
                self._mark_component("ollama", "needs_repair", str(e)[:200])

            # Models
            self._set_step("models", 50, "Checking language models…")
            try:
                from core.model_runtime import get_model_runtime
                rt = get_model_runtime()
                if simulate_no_ollama or simulate_offline:
                    self._mark_component("models", "needs_repair", "Simulated: skipped model pull")
                    pull = {"ok": False}
                else:
                    with StepWatchdog("bg_pull_models"):
                        pull = rt.install_required_models()
                self._mark_component(
                    "models",
                    "installed" if pull.get("ok") else "needs_repair",
                    pull.get("user_message", ""),
                )
            except Exception as e:
                self._mark_component("models", "needs_repair", str(e)[:200])

            # Dependencies
            self._set_step("dependencies", 70, "Checking optional dependencies…")
            try:
                from core.dependency_manager import get_dependency_manager
                dm = get_dependency_manager()
                with StepWatchdog("bg_dependencies"):
                    inst = dm.install_all_required()
                for cid, res in (inst.get("results") or {}).items():
                    st = "installed" if res.get("ok") or res.get("skipped") else "needs_repair"
                    self._mark_component(cid, st)
            except Exception as e:
                self._mark_component("dependencies", "needs_repair", str(e)[:200])

            # Validation (best effort)
            self._set_step("validation", 85, "Testing local inference…")
            try:
                from core.model_runtime import get_model_runtime
                with StepWatchdog("bg_validate"):
                    val = get_model_runtime().validate_inference()
                self._mark_component(
                    "inference",
                    "installed" if val.get("ok") else "needs_repair",
                    val.get("user_message", ""),
                )
            except Exception as e:
                self._mark_component("inference", "needs_repair", str(e)[:200])

            self._set_step("ready", 100, "Sentinel is ready — background setup finished")
            self.force_complete(allow_degraded=True)

    def force_complete(self, allow_degraded: bool = True) -> Dict[str, Any]:
        with StepWatchdog("force_complete", allow_degraded=allow_degraded):
            from core.onboarding.first_launch import get_first_launch
            fl = get_first_launch()
            fl.mark_completed(allow_degraded=allow_degraded, components=self._state.get("components", {}))
            with _LOCK:
                self._state["completed"] = True
                self._state["allow_chat"] = True
                self._state["percent"] = 100
                self._save()
            return {"ok": True, "allow_chat": True, "progress": self.progress()}


_pipeline: Optional[OnboardingPipeline] = None


def get_onboarding_pipeline() -> OnboardingPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = OnboardingPipeline()
    return _pipeline
