"""
Metasploit Framework wrapper (msfconsole subprocess).
Only available in ATTACK mode.
INVARIANT: authorized_target must be explicitly confirmed before any execution.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MetasploitResult:
    success: bool
    output: str = ""
    module: str = ""
    findings: List[Dict] = field(default_factory=list)
    error: Optional[str] = None


class MetasploitTool:
    """
    Wraps Metasploit Framework via msfconsole subprocess.
    Only for ATTACK mode. Requires explicit authorization.
    """

    def __init__(self, socketio: Any = None):
        self.socketio = socketio

    def _emit(self, message: str, level: str = "info") -> None:
        if self.socketio:
            try:
                self.socketio.emit("log_event", {
                    "type": "guardian",
                    "level": level,
                    "message": f"[MSF] {message}",
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception:
                pass

    def is_available(self) -> bool:
        return bool(shutil.which("msfconsole") or shutil.which("msfconsole.bat"))

    def run_module(self, module: str, options: Dict[str, str],
                   authorized_target: str) -> MetasploitResult:
        """
        Run a specific MSF module against an authorized target.
        INVARIANT: authorized_target must be explicitly confirmed.
        """
        if not authorized_target:
            return MetasploitResult(
                success=False,
                error="Authorization required: no target confirmed",
            )

        msf_bin = shutil.which("msfconsole") or shutil.which("msfconsole.bat")
        if not msf_bin:
            return MetasploitResult(success=False, error="msfconsole not in PATH")

        # Build RC script
        rc_lines = [f"use {module}"]
        for key, val in options.items():
            rc_lines.append(f"set {key} {val}")
        rc_lines += ["run", "exit -y"]
        rc_script = "\n".join(rc_lines)

        self._emit(f"Running module: {module} against {authorized_target}")

        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".rc", delete=False, encoding="utf-8") as tmp:
                tmp.write(rc_script)
                rc_path = tmp.name

            proc = subprocess.run(
                [msf_bin, "-q", "-r", rc_path],
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = (proc.stdout or "") + (proc.stderr or "")
            self._emit(output[:500], "info")
            return MetasploitResult(
                success=proc.returncode == 0,
                output=output,
                module=module,
            )
        except subprocess.TimeoutExpired:
            msg = "msfconsole timed out (120s)"
            self._emit(msg, "error")
            return MetasploitResult(success=False, error=msg, module=module)
        except Exception as e:
            self._emit(str(e), "error")
            return MetasploitResult(success=False, error=str(e), module=module)

    def search_exploits(self, cve: str) -> List[Dict]:
        """Search for exploits matching a CVE identifier."""
        msf_bin = shutil.which("msfconsole") or shutil.which("msfconsole.bat")
        if not msf_bin:
            return []
        try:
            proc = subprocess.run(
                [msf_bin, "-q", "-x", f"search {cve}; exit"],
                capture_output=True, text=True, timeout=30,
            )
            results = []
            for line in (proc.stdout or "").splitlines():
                if cve.lower() in line.lower() and ("exploit" in line.lower() or "auxiliary" in line.lower()):
                    results.append({"module": line.strip(), "cve": cve})
            return results
        except Exception as e:
            logger.debug("MSF search failed: %s", e)
            return []
