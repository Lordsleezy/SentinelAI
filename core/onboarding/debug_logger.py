"""Structured onboarding diagnostics -> data/onboarding/onboarding_debug.log"""
from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

_ROOT = Path(__file__).resolve().parents[2]
_LOG_PATH = _ROOT / "data" / "onboarding" / "onboarding_debug.log"

logger = logging.getLogger("sentinel.onboarding.debug")


def _ensure_log() -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def log_event(
    step: str,
    *,
    phase: str = "step",
    success: Optional[bool] = None,
    duration_ms: Optional[float] = None,
    detail: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    stack: Optional[str] = None,
) -> None:
    _ensure_log()
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "phase": phase,
        "step": step,
        "success": success,
        "duration_ms": round(duration_ms, 2) if duration_ms is not None else None,
        "detail": detail or {},
        "error": error,
        "stack": stack,
    }
    line = json.dumps(entry, default=str)
    with _LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    if success is False:
        logger.warning("onboarding step failed: %s — %s", step, error or detail)
    else:
        logger.info("onboarding %s: %s (%.0fms)", phase, step, duration_ms or 0)


class StepWatchdog:
    """Context manager: logs start/end, duration, exceptions with stack traces."""

    def __init__(self, step: str, **detail: Any) -> None:
        self.step = step
        self.detail = detail
        self._t0 = 0.0

    def __enter__(self) -> "StepWatchdog":
        self._t0 = datetime.now(timezone.utc).timestamp()
        log_event(self.step, phase="start", detail=self.detail)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        duration_ms = (datetime.now(timezone.utc).timestamp() - self._t0) * 1000
        if exc_type is None:
            log_event(self.step, phase="end", success=True, duration_ms=duration_ms, detail=self.detail)
            return False
        log_event(
            self.step,
            phase="end",
            success=False,
            duration_ms=duration_ms,
            detail=self.detail,
            error=str(exc),
            stack="".join(traceback.format_exception(exc_type, exc, tb)),
        )
        return False  # do not suppress
