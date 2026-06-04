"""
First-party product analytics (install / trial) — separate from opt-in usage telemetry.
Never blocks startup; failures are retried on next launch where applicable.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_TELEMETRY_BASE = os.getenv("SENTINEL_TELEMETRY_URL", "https://sentinelprime.org").rstrip("/")
_INSTALL_ENDPOINT = f"{_TELEMETRY_BASE}/api/telemetry/install"
_TRIAL_ENDPOINT = f"{_TELEMETRY_BASE}/api/telemetry/trial"


def _user_data_dir() -> Path:
    try:
        from core.app_paths import resolve_user_data_dir
        return resolve_user_data_dir()
    except ImportError:
        appdata = os.environ.get("APPDATA", "").strip()
        if appdata:
            return Path(appdata) / "SentinelAI"
        return Path.home() / ".sentinelai"


def install_id_path() -> Path:
    return _user_data_dir() / "install_id"


def get_install_id() -> str:
    path = install_id_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        try:
            existing = path.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        except OSError:
            pass
    new_id = str(uuid.uuid4())
    try:
        path.write_text(new_id, encoding="utf-8")
    except OSError as exc:
        logger.debug("install_id write failed: %s", exc)
    return new_id


def _report_state_path() -> Path:
    return _user_data_dir() / "install_reported.json"


def _read_report_state() -> dict[str, Any]:
    p = _report_state_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_report_state(state: dict[str, Any]) -> None:
    try:
        _report_state_path().write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass


def _post_async(url: str, payload: dict[str, Any]) -> None:
    def _send() -> None:
        try:
            import httpx
            httpx.post(url, json=payload, timeout=8.0)
        except Exception as exc:
            logger.debug("product analytics POST failed: %s", exc)

    threading.Thread(target=_send, daemon=True, name="product-analytics").start()


def report_trial_start(started_at: Optional[str] = None) -> None:
    from datetime import datetime, timezone
    ts = started_at or datetime.now(timezone.utc).isoformat()
    _post_async(_TRIAL_ENDPOINT, {"install_id": get_install_id(), "started_at": ts})


def report_install_once(
    *,
    version: str,
    os_name: str,
    arch: str,
    trial_start: bool = True,
) -> None:
    """Report first install once; retry once on next launch if the first attempt failed."""
    state = _read_report_state()
    if state.get("sent"):
        return
    if state.get("failed") and state.get("retried"):
        return

    from datetime import datetime, timezone
    payload = {
        "install_id": get_install_id(),
        "version": version,
        "os": os_name,
        "arch": arch,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trial_start": trial_start,
    }

    def _attempt() -> None:
        try:
            import httpx
            r = httpx.post(_INSTALL_ENDPOINT, json=payload, timeout=8.0)
            if r.status_code < 300:
                _write_report_state({"sent": True})
                return
        except Exception as exc:
            logger.debug("install report failed: %s", exc)
        if state.get("failed"):
            _write_report_state({"sent": False, "failed": True, "retried": True})
        else:
            _write_report_state({"sent": False, "failed": True, "retried": False})

    threading.Thread(target=_attempt, daemon=True, name="install-report").start()
