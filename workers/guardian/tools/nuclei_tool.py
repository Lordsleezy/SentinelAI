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
        for candidate in _NUCLEI_PATHS:
            found = shutil.which(candidate) or (
                candidate if candidate.startswith(r"C:\") and __import__("os").path.isfile(candidate) else None
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
             severity: Optional[List[str]] = None) -> NucleiResult:
        """
        Run nuclei scan against target.
        Default templates: cves, vulnerabilities, exposures.
        Default severity: critical, high, medium.
        """
        bin_path = self._get_bin()
        if not bin_path:
            return NucleiResult(success=False, error="Nuclei not installed")

        templates = templates or ["cves", "vulnerabilities", "exposures"]
        severity = severity or ["critical", "high", "medium"]

        cmd = [
            bin_path,
            "-u", target,
            "-t", ",".join(templates),
            "-severity", ",".join(severity),
            "-json",
            "-silent",
            "-no-color",
        ]

        self._emit(f"Scanning {target} with templates: {', '.join(templates)}")
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
                if not line:
                    continue
                raw_lines.append(line)
                self._emit(line)

            proc.wait(timeout=300)
            raw_output = "\n".join(raw_lines)
            findings = self.parse_output(raw_output)
            self._emit(f"Found {len(findings)} issues", "success" if findings else "info")
            return NucleiResult(success=True, findings=findings, raw_output=raw_output)

        except subprocess.TimeoutExpired:
            msg = "Nuclei scan timed out (5m)"
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
