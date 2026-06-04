"""
Wearables Integration — Open Wearables API.

Until a real Open Wearables endpoint is wired up, every getter returns a
"not connected" envelope so the UI can render a clear configuration prompt
instead of fabricated biometric data.
"""
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

try:
    import httpx  # noqa: F401  (reserved for the real API call)
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


_NOT_CONNECTED_MSG = (
    "No wearable connected. You can connect Apple Health, Fitbit, or Garmin in Settings."
)


def _not_connected(extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "error": "No wearable connected",
        "message": _NOT_CONNECTED_MSG,
        "data": None,
    }
    if extra:
        payload.update(extra)
    return payload


def _httpx_missing() -> Dict[str, Any]:
    return {
        "error": "httpx not available",
        "message": "httpx is required to talk to the Open Wearables API.",
        "data": None,
    }


def get_sleep_data(days: int = 7) -> Dict[str, Any]:
    """Sleep summary from the connected wearable.

    Returns a not-connected envelope when OPEN_WEARABLES_TOKEN is unset
    (or when no real provider is wired up yet). Callers must treat
    ``data is None`` as "no data" rather than zero.
    """
    if not os.getenv("OPEN_WEARABLES_TOKEN"):
        return _not_connected()
    if not HTTPX_AVAILABLE:
        return _httpx_missing()
    # Real Open Wearables call goes here. Until it is implemented we report
    # the integration as unavailable rather than fabricate numbers.
    return {
        "error": "Open Wearables provider not implemented",
        "message": _NOT_CONNECTED_MSG,
        "data": None,
    }


def get_activity_data(days: int = 7) -> Dict[str, Any]:
    if not os.getenv("OPEN_WEARABLES_TOKEN"):
        return _not_connected()
    if not HTTPX_AVAILABLE:
        return _httpx_missing()
    return {
        "error": "Open Wearables provider not implemented",
        "message": _NOT_CONNECTED_MSG,
        "data": None,
    }


def get_heart_rate(days: int = 1) -> Dict[str, Any]:
    if not os.getenv("OPEN_WEARABLES_TOKEN"):
        return _not_connected()
    if not HTTPX_AVAILABLE:
        return _httpx_missing()
    return {
        "error": "Open Wearables provider not implemented",
        "message": _NOT_CONNECTED_MSG,
        "data": None,
    }


def get_health_summary() -> Dict[str, Any]:
    """Comprehensive health summary.

    Returns a not-connected envelope until a real provider is configured.
    """
    if not os.getenv("OPEN_WEARABLES_TOKEN"):
        return {
            "error": "No wearable connected",
            "message": _NOT_CONNECTED_MSG,
            "summary": _NOT_CONNECTED_MSG,
            "sleep_hours": None,
            "steps_today": None,
            "resting_hr": None,
        }

    sleep = get_sleep_data(days=1)
    activity = get_activity_data(days=1)
    hr = get_heart_rate(days=1)

    # All three currently report "not implemented" — surface that to the UI
    # instead of pretending we have data.
    return {
        "error": "Open Wearables provider not implemented",
        "message": _NOT_CONNECTED_MSG,
        "summary": _NOT_CONNECTED_MSG,
        "sleep_hours": (sleep.get("data") or {}).get("avg_sleep_hours"),
        "steps_today": (activity.get("data") or {}).get("steps_today"),
        "resting_hr": (hr.get("data") or {}).get("resting_hr"),
    }
