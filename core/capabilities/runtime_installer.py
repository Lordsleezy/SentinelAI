"""
Runtime Installer — on-demand installs delegated to existing Sentinel modules.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from core.capabilities.runtime_validator import validate_capability

logger = logging.getLogger("sentinel.capabilities.installer")

LogFn = Optional[Callable[[str, str], None]]


def install_capability(capability_id: str, log_fn: LogFn = None) -> Dict[str, Any]:
    """Install a capability by id. Returns {ok, error?, ...}."""
    cid = capability_id.lower()

    def _log(msg: str, level: str = "info") -> None:
        logger.info(msg)
        if log_fn:
            log_fn(msg, level)

    if cid == "godot":
        from builders.runtime.godot_runtime import install_godot
        return install_godot(log_fn=log_fn)

    if cid == "godot_export_templates":
        _log("Export templates: optional — skipped for editor launch")
        return {"ok": True, "skipped": True}

    if cid == "ollama" or cid == "ollama_models":
        try:
            from workers.guardian.runtime_manager import pull_model
            return pull_model("dolphin3:8b")
        except Exception as e:
            return {"ok": False, "error": str(e)}

    if cid in ("httpx", "subfinder", "katana", "nuclei", "dnsx", "naabu", "ffuf",
               "assetfinder", "amass", "gowitness", "zap"):
        try:
            from workers.guardian.bootstrap_manager import run_bootstrap
            result = run_bootstrap(log_fn=log_fn)
            v = validate_capability(cid)
            if v.installed:
                return {"ok": True, "capability": cid, **result}
            return {"ok": False, "error": f"{cid} still missing after bootstrap", **result}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    if cid in ("nodejs", "npm", "electron", "playwright"):
        _log(f"{cid}: use system Node installer or Sentinel installer bundle (Tier 1)")
        v = validate_capability(cid)
        if v.installed:
            return {"ok": True, "skipped": True, "message": v.message}
        return {
            "ok": False,
            "error": f"{cid} not found. Install Node.js from sentinel installer or https://nodejs.org",
        }

    if cid.startswith("android") or cid in ("jdk", "gradle"):
        return {"ok": False, "error": f"{cid} — Android toolchain install on demand (Tier 3) not bundled yet"}

    v = validate_capability(cid)
    if v.installed:
        return {"ok": True, "skipped": True}
    return {"ok": False, "error": f"No installer for {cid}"}
