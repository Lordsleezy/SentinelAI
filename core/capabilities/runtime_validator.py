"""
Runtime Validator — health checks for each capability id.
"""
from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class ValidationResult:
    capability_id: str
    installed: bool
    healthy: bool
    version: str = ""
    message: str = ""
    path: str = ""
    last_verified: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.capability_id,
            "installed": self.installed,
            "healthy": self.healthy,
            "version": self.version,
            "message": self.message,
            "path": self.path,
            "last_verified": self.last_verified,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_capability(capability_id: str) -> ValidationResult:
    """Run a single capability health check."""
    cid = capability_id.lower()
    ts = _now_iso()

    if cid == "python":
        return ValidationResult(
            cid, True, True, f"{sys.version_info.major}.{sys.version_info.minor}",
            "Python runtime", sys.executable, ts,
        )
    if cid in ("git",):
        p = shutil.which("git")
        return ValidationResult(cid, bool(p), bool(p), "", "git in PATH" if p else "git missing", p or "", ts)
    if cid in ("nodejs",):
        p = shutil.which("node")
        return ValidationResult(cid, bool(p), bool(p), "", "node in PATH" if p else "node missing", p or "", ts)
    if cid in ("npm",):
        p = shutil.which("npm")
        return ValidationResult(cid, bool(p), bool(p), "", "npm in PATH" if p else "npm missing", p or "", ts)
    if cid == "sqlite":
        return ValidationResult(cid, True, True, "", "stdlib sqlite3", "", ts)
    if cid == "venv":
        if getattr(sys, "frozen", False):
            return ValidationResult(
                cid, True, True, "",
                "bundled PyInstaller runtime (no project venv required)",
                sys.executable, ts,
            )
        root = Path(__file__).resolve().parents[2]
        venv_py = root / "venv" / ("Scripts" if sys.platform == "win32" else "bin") / (
            "python.exe" if sys.platform == "win32" else "python"
        )
        ok = venv_py.is_file()
        return ValidationResult(cid, ok, ok, "", "project venv" if ok else "venv missing", str(venv_py) if ok else "", ts)
    if cid == "godot":
        try:
            from builders.runtime.godot_runtime import godot_diagnostic
            d = godot_diagnostic()
            ok = bool(d.get("installed"))
            return ValidationResult(
                cid, ok, ok, "",
                d.get("status_line", ""),
                str(d.get("path") or ""),
                ts,
            )
        except Exception as e:
            return ValidationResult(cid, False, False, "", str(e), "", ts)
    if cid == "ollama":
        try:
            from workers.guardian.runtime_manager import get_brain_status
            brain = get_brain_status()
            ok = bool(brain.get("ollama_running") or brain.get("installed"))
            return ValidationResult(
                cid, ok, ok, "",
                brain.get("status_line", "Ollama"),
                "",
                ts,
            )
        except Exception as e:
            return ValidationResult(cid, False, False, "", str(e), "", ts)
    if cid in ("httpx", "subfinder", "katana", "nuclei", "dnsx", "naabu", "ffuf",
               "assetfinder", "amass", "gowitness", "zap"):
        try:
            from workers.guardian.bundled_toolchain import diagnose_core_tool
            if cid in ("httpx", "subfinder", "katana", "nuclei", "dnsx", "naabu"):
                diag = diagnose_core_tool(cid)
            else:
                from workers.guardian.guardian_tool_registry_store import refresh_registry
                tools = (refresh_registry().get("tools") or {}).get(cid) or {}
                diag = {
                    "installed": tools.get("install_status") == "installed",
                    "path": tools.get("install_path"),
                    "status_line": tools.get("status_line", ""),
                    "version": tools.get("version"),
                }
            ok = bool(diag.get("installed"))
            return ValidationResult(
                cid, ok, ok,
                str(diag.get("version") or ""),
                str(diag.get("status_line") or ""),
                str(diag.get("path") or ""),
                ts,
            )
        except Exception:
            which = shutil.which(cid)
            ok = bool(which)
            return ValidationResult(cid, ok, ok, "", f"{cid} in PATH" if ok else f"{cid} missing", which or "", ts)
    if cid == "electron":
        npm = shutil.which("npm")
        return ValidationResult(cid, bool(npm), bool(npm), "", "via npm" if npm else "npm required", "", ts)
    if cid == "playwright":
        npm = shutil.which("npm")
        return ValidationResult(cid, bool(npm), bool(npm), "", "install per project", "", ts)

    return ValidationResult(cid, True, True, "", "No validator — assumed optional", "", ts)
