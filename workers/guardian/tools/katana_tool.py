"""
workers/guardian/tools/katana_tool.py — ProjectDiscovery Katana wrapper
Install: https://github.com/projectdiscovery/katana/releases
Use: deep endpoint / route discovery. Feeds into Nuclei for targeted scans.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional

_KATANA_PATHS = [r"C:\Tools\katana.exe", "katana", "katana.exe"]


@dataclass
class KatanaResult:
    success: bool
    endpoints: List[str] = field(default_factory=list)
    raw_output: str = ""
    error: Optional[str] = None


class KatanaTool:
    """
    Runs Katana for endpoint and route discovery (deep crawl).
    Discovered endpoints are fed into Nuclei for targeted vulnerability scanning.
    """

    def __init__(self, socketio: Any = None):
        self.socketio = socketio
        self._bin: Optional[str] = None

    def _get_bin(self) -> Optional[str]:
        if self._bin:
            return self._bin
        try:
            from workers.guardian.bundled_toolchain import resolve_tool_binary
            resolved = resolve_tool_binary("katana")
            if resolved:
                self._bin = resolved.path
                return self._bin
        except Exception:
            pass
        for c in _KATANA_PATHS:
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
                    "message": f"[Katana] {msg}",
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception:
                pass

    def crawl(self, target_url: str, depth: int = 3, timeout: int = 120) -> KatanaResult:
        """
        Deep crawl target_url to discover endpoints and routes.
        depth: crawl depth (default 3)
        Returns list of discovered URLs.
        """
        bin_path = self._get_bin()
        if not bin_path:
            return KatanaResult(success=False, error="Katana not installed — skipping")

        # Ensure target has a scheme
        if not target_url.startswith(("http://", "https://")):
            target_url = f"https://{target_url}"

        cmd = [
            bin_path,
            "-u", target_url,
            "-d", str(depth),
            "-silent", "-no-color",
            "-timeout", str(timeout // 10),  # per-request timeout
        ]
        self._emit(f"Crawling {target_url} (depth={depth})…")
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout,
            )
            endpoints = [l.strip() for l in proc.stdout.splitlines() if l.strip()]
            for ep in endpoints[:20]:    # emit first 20 to avoid log spam
                self._emit(ep)
            if len(endpoints) > 20:
                self._emit(f"… and {len(endpoints) - 20} more endpoints")
            self._emit(f"Discovered {len(endpoints)} endpoint(s)", "success" if endpoints else "info")
            return KatanaResult(success=True, endpoints=endpoints, raw_output=proc.stdout)
        except subprocess.TimeoutExpired:
            msg = f"Katana timed out ({timeout}s)"
            self._emit(msg, "error")
            return KatanaResult(success=False, error=msg)
        except Exception as e:
            self._emit(str(e), "error")
            return KatanaResult(success=False, error=str(e))
