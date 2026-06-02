"""
workers/guardian/tools/amass_tool.py — OWASP Amass wrapper
Install: https://github.com/owasp-amass/amass/releases
Use: DNS mapping, infrastructure mapping, relationship discovery.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

_AMASS_PATHS = [r"C:\Tools\amass.exe", "amass", "amass.exe"]


@dataclass
class AmassResult:
    success: bool
    assets: List[Dict] = field(default_factory=list)   # {name, type, addresses}
    raw_output: str = ""
    error: Optional[str] = None


class AmassTool:
    """
    Runs OWASP Amass for DNS/infrastructure mapping and relationship discovery.
    Generates infrastructure overview: subdomains, IPs, ASNs, related domains.
    """

    def __init__(self, socketio: Any = None):
        self.socketio = socketio
        self._bin: Optional[str] = None

    def _get_bin(self) -> Optional[str]:
        if self._bin:
            return self._bin
        for c in _AMASS_PATHS:
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
                    "message": f"[Amass] {msg}",
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception:
                pass

    def enum_passive(self, domain: str, timeout: int = 120) -> AmassResult:
        """
        Passive DNS enumeration — no active probing.
        Returns subdomains, IPs, and relationship data.
        """
        bin_path = self._get_bin()
        if not bin_path:
            return AmassResult(success=False, error="Amass not installed — skipping")

        cmd = [bin_path, "enum", "-passive", "-d", domain, "-nocolor"]
        self._emit(f"DNS mapping for {domain} (passive)…")
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout,
            )
            lines = [l.strip() for l in proc.stdout.splitlines() if l.strip()]
            assets: List[Dict] = []
            for ln in lines:
                self._emit(ln)
                assets.append({"name": ln, "type": "subdomain"})
            self._emit(f"Mapped {len(assets)} DNS asset(s)", "success" if assets else "info")
            return AmassResult(success=True, assets=assets, raw_output=proc.stdout)
        except subprocess.TimeoutExpired:
            msg = f"Amass timed out ({timeout}s)"
            self._emit(msg, "error")
            return AmassResult(success=False, error=msg)
        except Exception as e:
            self._emit(str(e), "error")
            return AmassResult(success=False, error=str(e))
