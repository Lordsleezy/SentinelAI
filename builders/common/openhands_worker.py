"""
Optional OpenHands builder worker — https://github.com/All-Hands-AI/OpenHands

When OpenHands is not installed, returns gracefully; Forge uses native builders.
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Any, Optional

from builders.common.logging_util import log_builder
from builders.common.types import BuildResult


def is_openhands_available() -> bool:
    return bool(shutil.which("openhands") or shutil.which("docker"))


def run_openhands_session(
    description: str,
    output_dir: str,
    socketio: Any = None,
    timeout: int = 300,
) -> Optional[BuildResult]:
    """
    Attempt an OpenHands-assisted build. Returns None if unavailable or failed.
    """
    if not is_openhands_available():
        log_builder("OpenHands not available — using native builder", "info", socketio)
        return None

    log_builder("OpenHands session starting", "info", socketio)
    # CLI surface evolves; native builders remain primary path
    try:
        if shutil.which("openhands"):
            proc = subprocess.run(
                ["openhands", "--help"],
                capture_output=True, text=True, timeout=15,
            )
            if proc.returncode != 0:
                return None
            log_builder("OpenHands CLI detected — full session wiring is optional", "info", socketio)
    except Exception as e:
        log_builder(f"OpenHands probe failed: {e}", "warning", socketio)
    return None
