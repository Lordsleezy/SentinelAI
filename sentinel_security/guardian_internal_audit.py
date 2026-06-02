"""Layer 6 — Guardian Internal Mode: local Sentinel host health (not target scanning)."""
from __future__ import annotations

import logging
import platform
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from sentinel_security.config import ROOT
from sentinel_security.module_signing import verify_all
from sentinel_security.self_protection import check_integrity

logger = logging.getLogger("sentinel.security.internal_audit")


@dataclass
class HealthFinding:
    category: str
    severity: str
    summary: str
    detail: str = ""


@dataclass
class SecurityHealthReport:
    generated_at: str
    hostname: str
    findings: List[HealthFinding] = field(default_factory=list)
    open_ports: List[str] = field(default_factory=list)
    score: str = "HEALTHY"

    def to_markdown(self) -> str:
        lines = [
            "# Sentinel Security Health Report",
            "",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| Generated | {self.generated_at} |",
            f"| Host | {self.hostname} |",
            f"| Score | **{self.score}** |",
            "",
            "## Findings",
            "",
        ]
        if not self.findings:
            lines.append("No issues detected.")
        for f in self.findings:
            lines.append(f"- **[{f.severity}]** {f.category}: {f.summary}")
            if f.detail:
                lines.append(f"  - {f.detail[:200]}")
        if self.open_ports:
            lines += ["", "## Open Ports (sample)", ""]
            for p in self.open_ports[:30]:
                lines.append(f"- {p}")
        return "\n".join(lines)


def _run_netstat() -> List[str]:
    ports: List[str] = []
    try:
        if platform.system() == "Windows":
            proc = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace",
            )
            for line in (proc.stdout or "").splitlines():
                if "LISTENING" in line:
                    ports.append(line.strip()[:120])
        else:
            proc = subprocess.run(
                ["ss", "-tlnp"],
                capture_output=True, text=True, timeout=15,
            )
            ports = [ln.strip() for ln in (proc.stdout or "").splitlines() if "LISTEN" in ln]
    except Exception as e:
        logger.debug("netstat failed: %s", e)
    return ports[:50]


def _check_startup_entries() -> List[HealthFinding]:
    findings: List[HealthFinding] = []
    if platform.system() != "Windows":
        return findings
    try:
        proc = subprocess.run(
            ["reg", "query", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"],
            capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace",
        )
        if proc.returncode == 0 and proc.stdout:
            lines = [l for l in proc.stdout.splitlines() if "REG_" in l or ".exe" in l.lower()]
            if len(lines) > 25:
                findings.append(HealthFinding(
                    "persistence", "medium",
                    f"Many HKCU Run entries ({len(lines)})",
                    "Review startup entries for unexpected programs",
                ))
    except Exception:
        pass
    return findings


def _check_plugins_unsigned() -> List[HealthFinding]:
    findings: List[HealthFinding] = []
    plugins = ROOT / "plugins"
    if plugins.is_dir():
        for p in plugins.iterdir():
            if p.suffix == ".py" and not (p.with_suffix(".sig")).is_file():
                findings.append(HealthFinding(
                    "plugins", "low",
                    f"Unsigned plugin: {p.name}",
                    "No .sig sidecar — verify before enabling",
                ))
    return findings


def run_internal_audit() -> SecurityHealthReport:
    import socket
    report = SecurityHealthReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        hostname=socket.gethostname(),
    )
    report.open_ports = _run_netstat()

    unexpected = [p for p in report.open_ports if re.search(r":(4444|31337|6667)\s", p)]
    if unexpected:
        report.findings.append(HealthFinding(
            "network", "high",
            "Suspicious listening ports detected",
            "; ".join(unexpected[:3]),
        ))

    report.findings.extend(_check_startup_entries())
    report.findings.extend(_check_plugins_unsigned())

    integrity = check_integrity()
    if not integrity.ok:
        report.findings.append(HealthFinding(
            "integrity", "high",
            "Binary or module hash mismatch",
            "; ".join(a.message for a in integrity.alerts[:5]),
        ))

    for vr in verify_all():
        if not vr.ok:
            report.findings.append(HealthFinding(
                "signed_modules", "high",
                f"Module verification failed: {vr.module}",
                "; ".join(vr.failures[:3]),
            ))

    sev_order = {"high": 3, "medium": 2, "low": 1}
    score_val = sum(sev_order.get(f.severity, 0) for f in report.findings)
    if score_val >= 5:
        report.score = "CRITICAL"
    elif score_val >= 3:
        report.score = "ELEVATED"
    elif score_val >= 1:
        report.score = "ADVISORY"
    else:
        report.score = "HEALTHY"

    return report
