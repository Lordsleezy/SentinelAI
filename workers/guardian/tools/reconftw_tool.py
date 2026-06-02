"""
Reconftw automated recon framework wrapper.
https://github.com/six2dez/reconftw

Runs full recon pipeline: subdomain enum, port scan, tech detection,
vuln scan, screenshots.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

_RECONFTW_PATHS = [
    r"C:\Tools\reconftw\reconftw.sh",
    "/opt/reconftw/reconftw.sh",
    "reconftw.sh",
    "reconftw",
]


@dataclass
class ReconResult:
    success: bool
    domain: str = ""
    subdomains: List[str] = field(default_factory=list)
    open_ports: List[str] = field(default_factory=list)
    technologies: List[str] = field(default_factory=list)
    vulnerabilities: List[str] = field(default_factory=list)
    output_dir: str = ""
    raw_output: str = ""
    error: Optional[str] = None


class ReconftfTool:
    """
    Wraps Reconftw automated recon framework.
    Streams progress via Socket.IO.
    """

    def __init__(self, socketio: Any = None):
        self.socketio = socketio

    def _emit(self, message: str, level: str = "info") -> None:
        if self.socketio:
            try:
                self.socketio.emit("log_event", {
                    "type": "guardian",
                    "level": level,
                    "message": f"[Reconftw] {message}",
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception:
                pass

    def _get_bin(self) -> Optional[str]:
        for candidate in _RECONFTW_PATHS:
            if shutil.which(candidate):
                return candidate
            if os.path.isfile(candidate):
                return candidate
        return None

    def is_available(self) -> bool:
        return self._get_bin() is not None

    def _run(self, domain: str, flags: List[str]) -> ReconResult:
        bin_path = self._get_bin()
        if not bin_path:
            return ReconResult(success=False, domain=domain, error="reconftw not installed")

        output_dir = os.path.join(os.path.expanduser("~"), "reconftw_output", domain)
        os.makedirs(output_dir, exist_ok=True)

        cmd = [bin_path, "-d", domain, "-o", output_dir] + flags
        self._emit(f"Starting recon on {domain}")

        raw_lines: List[str] = []
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            for line in iter(proc.stdout.readline, ""):
                line = line.rstrip()
                if line:
                    raw_lines.append(line)
                    self._emit(line)
            proc.wait(timeout=1800)

            return ReconResult(
                success=proc.returncode == 0,
                domain=domain,
                output_dir=output_dir,
                raw_output="\n".join(raw_lines),
            )
        except subprocess.TimeoutExpired:
            msg = "Reconftw timed out (30m)"
            self._emit(msg, "error")
            return ReconResult(success=False, domain=domain, error=msg)
        except Exception as e:
            self._emit(str(e), "error")
            return ReconResult(success=False, domain=domain, error=str(e))

    def full_recon(self, domain: str) -> ReconResult:
        """Run full recon pipeline on domain."""
        return self._run(domain, ["-f"])

    def quick_recon(self, domain: str) -> ReconResult:
        """Faster subset — subdomains + ports only."""
        return self._run(domain, ["-s", "-p"])
