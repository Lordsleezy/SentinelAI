"""
workers/guardian/tools/httpx_tool.py — ProjectDiscovery httpx wrapper
Install: https://github.com/projectdiscovery/httpx/releases
Use: technology detection, status codes, headers, TLS, live host discovery.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

_HTTPX_PATHS = [r"C:\Tools\httpx.exe", "httpx", "httpx.exe"]


@dataclass
class HttpxResult:
    success: bool
    hosts: List[Dict] = field(default_factory=list)
    raw_output: str = ""
    error: Optional[str] = None


class HttpxTool:
    """
    Runs httpx for technology fingerprinting and live host discovery.
    Parses JSON-line output into structured host records.
    """

    def __init__(self, socketio: Any = None):
        self.socketio = socketio
        self._bin: Optional[str] = None

    def _get_bin(self) -> Optional[str]:
        if self._bin:
            return self._bin
        for c in _HTTPX_PATHS:
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
                    "message": f"[httpx] {msg}",
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception:
                pass

    def probe(self, targets: List[str], timeout: int = 10) -> HttpxResult:
        """
        Probe a list of hosts/URLs.  Returns technology, status codes, TLS info.
        targets may be hostnames, IPs, or full URLs.
        """
        bin_path = self._get_bin()
        if not bin_path:
            return HttpxResult(success=False, error="httpx not installed — skipping")

        cmd = [
            bin_path,
            "-json", "-silent", "-no-color",
            "-tech-detect",        # technology fingerprint
            "-status-code",
            "-title",
            "-follow-redirects",
            "-timeout", str(timeout),
        ]
        # httpx reads targets from stdin
        self._emit(f"Probing {len(targets)} host(s)…")
        raw_lines: List[str] = []
        proc = None
        per_target = max(timeout, 5) * len(targets) + 15
        run_timeout = min(max(per_target, 30), 90)
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
            )
            target_str = "\n".join(targets)
            stdout, stderr = proc.communicate(input=target_str, timeout=run_timeout)
            if stderr and stderr.strip():
                self._emit(f"stderr: {stderr.strip()[:300]}", "warning")
            for line in (stdout or "").splitlines():
                line = line.strip()
                if line:
                    raw_lines.append(line)
                    if line.startswith("{"):
                        self._emit(line[:200])

            hosts = self._parse(raw_lines)
            if not hosts:
                self._emit(
                    f"0 live hosts parsed from {len(targets)} target(s) "
                    f"({len(raw_lines)} raw line(s)) — pipeline continues",
                    "warning",
                )
            else:
                self._emit(f"Probed {len(hosts)} live host(s)", "success")
            return HttpxResult(success=True, hosts=hosts, raw_output="\n".join(raw_lines))
        except subprocess.TimeoutExpired:
            if proc:
                proc.kill()
            msg = f"httpx timed out ({run_timeout}s)"
            self._emit(msg, "error")
            return HttpxResult(success=False, error=msg, hosts=[])
        except Exception as e:
            self._emit(str(e), "error")
            return HttpxResult(success=False, error=str(e))

    def _parse(self, lines: List[str]) -> List[Dict]:
        hosts = []
        for line in lines:
            if not line.startswith("{"):
                continue
            try:
                d = json.loads(line)
                hosts.append({
                    "url":          d.get("url", ""),
                    "status_code":  d.get("status-code", 0),
                    "title":        d.get("title", ""),
                    "tech":         d.get("tech", []),
                    "tls":          d.get("tls", {}),
                    "webserver":    d.get("webserver", ""),
                    "content_type": d.get("content-type", ""),
                })
            except json.JSONDecodeError:
                continue
        return hosts
