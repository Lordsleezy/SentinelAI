"""Freqtrade manager — supervises a paper-trading bot (dry_run guard enforced).

Minimal scaffold. Spawns Freqtrade in dry-run mode only and exposes start /
stop / status helpers. Never calls Freqtrade with ``--live`` in this build.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_PROCESS: Optional[subprocess.Popen] = None  # type: ignore[type-arg]
DRY_RUN = os.getenv("SENTINEL_MARKET_LIVE", "false").lower() != "true"


def _freqtrade_path() -> Optional[str]:
    return shutil.which("freqtrade")


def status() -> Dict[str, Any]:
    """Return current Freqtrade supervisor status."""
    global _PROCESS
    if _PROCESS is None:
        return {"running": False, "pid": None, "dry_run": DRY_RUN}
    if _PROCESS.poll() is None:
        return {"running": True, "pid": _PROCESS.pid, "dry_run": DRY_RUN}
    _PROCESS = None
    return {"running": False, "pid": None, "dry_run": DRY_RUN}


def start(config_path: str = "user_data/config.json") -> Dict[str, Any]:
    """Start Freqtrade in dry-run mode. Returns a structured result dict."""
    global _PROCESS
    if not DRY_RUN:
        return {"status": "refused", "message":
                "Freqtrade live mode is disabled in this build"}
    if _PROCESS and _PROCESS.poll() is None:
        return {"status": "already_running", "pid": _PROCESS.pid}
    binary = _freqtrade_path()
    if not binary:
        return {"status": "unavailable",
                "message": "freqtrade not installed on PATH"}
    try:
        _PROCESS = subprocess.Popen(
            [binary, "trade", "--config", config_path, "--dry-run"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return {"status": "started", "pid": _PROCESS.pid, "dry_run": True}
    except Exception as exc:
        logger.debug("freqtrade start failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def stop() -> Dict[str, Any]:
    """Terminate the Freqtrade process if running."""
    global _PROCESS
    if _PROCESS is None or _PROCESS.poll() is not None:
        return {"status": "not_running"}
    try:
        _PROCESS.terminate()
        _PROCESS.wait(timeout=5)
    except Exception:
        try:
            _PROCESS.kill()
        except Exception:
            pass
    _PROCESS = None
    return {"status": "stopped"}
