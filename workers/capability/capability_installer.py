"""
Capability Installer — installs PyPI packages and registers them.

Minimal implementation. ``pip install`` is gated by an explicit approval flag so
no package is installed without user consent. Returns a structured result dict.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from typing import Any, Dict

from .registry import register_capability

logger = logging.getLogger(__name__)


def install(package_name: str, approved: bool = False) -> Dict[str, Any]:
    """Install a PyPI package and register it as a capability.

    Returns ``{"status": "ok"|"denied"|"error", ...}``. Never raises.
    """
    if not approved:
        return {"status": "denied", "package": package_name,
                "message": "Installation requires explicit approval"}
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", package_name],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            logger.warning("pip install %s failed: %s", package_name, result.stderr[:500])
            return {"status": "error", "package": package_name,
                    "stderr": result.stderr[-2000:]}
    except Exception as exc:
        return {"status": "error", "package": package_name, "error": str(exc)}

    register_capability(package_name, {"provider": "pypi", "status": "installed"})
    return {"status": "ok", "package": package_name}
