"""
Nuclei vulnerability scanner wrapper.
Install: https://github.com/projectdiscovery/nuclei/releases
Expected at C:\Tools\nuclei.exe or anywhere in PATH.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

_NUCLEI_PATHS = [
    r"C:\Tools\nuclei.exe",
    "nuclei",
    "nuclei.exe",
]


@dataclass
class Finding:
    template: str
    severity: str
    target: str
    description: str
    reference: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "template": self.template,
            "severity": self.severity,
            "target": self.target,
            "description": self.description,
            "reference": self.reference,
            "timestamp": self.timestamp,
        }


@dataclass
class NucleiResult:
    success: bool
    findings: List[Finding] = field(default_factory=list)
    raw_output: str = ""
    error: Optional[str] = None


class NucleiTool:
    """
    Wraps Nuclei vulnerability scanner.
    Streams output via Socket.IO log_event when socketio is provided.
    """

    def __init__(self, socketio: Any = None):
        self.socketio = socketio
        self._bin: Optional[str] = None

    def _get_bin(self) -> Optional[str]:
        if self._bin:
            return self._bin
        try:
            from workers.guardian.bundled_toolchain import resolve_tool_binary
            resolved = resolve_tool_binary("nuclei")
            if resolved:
                self._bin = resolved.path
                return self._bin
        except Exception:
            pass
        for candidate in _NUCLEI_PATHS:
            found = shutil.which(candidate) or (
                candidate if candidate.startswith("C:\\") and __import__("os").path.isfile(candidate) else None
            )
            if found:
                self._bin = found
                return found
        return None

    def is_available(self) -> bool:
        return self._get_bin() is not None

    def _emit(self, message: str, level: str = "info") -> None:
        if self.socketio:
            try:
                self.socketio.emit("log_event", {
                    "type": "guardian",
                    "level": level,
                    "message": f"[Nuclei] {message}",
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception:
                pass

    def scan(self, target: str, templates: Optional[List[str]] = None,
             severity: Optional[List[str]] = None,
             tags: Optional[str] = None) -> NucleiResult:
        """
        Run nuclei scan against target.
        Default templates: cves, vulnerabilities, exposures.
        Default severity: critical, high, medium.
        Optional tags: comma-separated Nuclei tags (overrides -t when set).
        """
        bin_path = self._get_bin()
        if not bin_path:
            return NucleiResult(success=False, error="Nuclei not installed")

        severity = severity or ["critical", "high", "medium"]

        cmd = [
            bin_path,
            "-u", target,
            "-severity", ",".join(severity),
            "-json",
            "-silent",
            "-no-color",
        ]
        if tags:
            cmd.extend(["-tags", tags])
            self._emit(f"Scanning with tags: {tags[:60]}…")
        else:
            templates = templates or ["cves", "vulnerabilities", "exposures"]
            cmd.extend(["-t", ",".join(templates)])

        scan_url = target if target.startswith(('http://', 'https://')) else f"https://{target}"
        cmd[cmd.index('-u') + 1] = scan_url

        self._emit(f"Scanning {scan_url} (timeout 90s)…")
        raw_lines: List[str] = []

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
            )
            raw_output = (proc.stdout or "") + (proc.stderr or "")
            for line in raw_output.splitlines():
                line = line.rstrip()
                if line:
                    raw_lines.append(line)
                    if line.startswith("{"):
                        self._emit(line[:200])
            findings = self.parse_output("\n".join(raw_lines))
            self._emit(f"Found {len(findings)} issues", "success" if findings else "info")
            return NucleiResult(success=True, findings=findings, raw_output=raw_output[:8000])

        except subprocess.TimeoutExpired:
            msg = "Nuclei scan timed out (90s)"
            self._emit(msg, "error")
            return NucleiResult(success=False, error=msg)
        except Exception as e:
            self._emit(str(e), "error")
            return NucleiResult(success=False, error=str(e))

    def parse_output(self, raw: str) -> List[Finding]:
        """Parse nuclei JSON-line output into Finding objects."""
        findings: List[Finding] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                data = json.loads(line)
                info = data.get("info", {})
                findings.append(Finding(
                    template=data.get("template-id", "unknown"),
                    severity=info.get("severity", "unknown"),
                    target=data.get("host", data.get("matched-at", "")),
                    description=info.get("description", info.get("name", "")),
                    reference=info.get("reference", []),
                ))
            except json.JSONDecodeError:
                continue
        return findings
