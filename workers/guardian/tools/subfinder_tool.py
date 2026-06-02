"""
workers/guardian/tools/subfinder_tool.py — ProjectDiscovery Subfinder wrapper
Install: https://github.com/projectdiscovery/subfinder/releases
Use: subdomain enumeration. Results feed into httpx, Nuclei, Katana.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional

_SUBFINDER_PATHS = [r"C:\Tools\subfinder.exe", "subfinder", "subfinder.exe"]


@dataclass
class SubfinderResult:
    success: bool
    subdomains: List[str] = field(default_factory=list)
    raw_output: str = ""
    error: Optional[str] = None


class SubfinderTool:
    """
    Runs Subfinder for passive subdomain enumeration.
    Results can be chained into httpx → Nuclei.
    """

    def __init__(self, socketio: Any = None):
        self.socketio = socketio
        self._bin: Optional[str] = None

    def _get_bin(self) -> Optional[str]:
        if self._bin:
            return self._bin
        for c in _SUBFINDER_PATHS:
            found = shutil.which(c) or (
                c if c.startswith("C:\\") and __import__("os").path.isfile(c) else None
            )
            if found:
                self._bin = found
                return found
        return None

    def is_available(self) -> bool:
        return self._get_bin() is not None

    def _emit(self, msg: str, level: str = "info") -> None:
        if self.socketio:
            try:
                self.socketio.emit("log_event", {
                    "type": "guardian", "level": level,
                    "message": f"[Subfinder] {msg}",
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception:
                pass

    def enumerate(self, domain: str, timeout: int = 60) -> SubfinderResult:
        """
        Enumerate subdomains for domain using passive sources.
        Returns a list of discovered subdomains.
        """
        bin_path = self._get_bin()
        if not bin_path:
            return SubfinderResult(success=False, error="Subfinder not installed — skipping")

        cmd = [bin_path, "-d", domain, "-silent", "-no-color"]
        self._emit(f"Enumerating subdomains for {domain}…")
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout,
            )
            lines = [l.strip() for l in proc.stdout.splitlines() if l.strip()]
            for ln in lines:
                self._emit(ln)
            self._emit(f"Found {len(lines)} subdomain(s)", "success" if lines else "info")
            return SubfinderResult(success=True, subdomains=lines, raw_output=proc.stdout)
        except subprocess.TimeoutExpired:
            msg = f"Subfinder timed out ({timeout}s)"
            self._emit(msg, "error")
            return SubfinderResult(success=False, error=msg)
        except Exception as e:
            self._emit(str(e), "error")
            return SubfinderResult(success=False, error=str(e))
