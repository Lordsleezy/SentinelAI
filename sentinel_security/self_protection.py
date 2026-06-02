"""Layer 10 — Tamper detection and verified restore hints."""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from sentinel_security.config import ROOT, SECURITY_DIR
from sentinel_security.module_signing import build_manifest, verify_all

logger = logging.getLogger("sentinel.security.self_protection")

BASELINE_PATH = SECURITY_DIR / "integrity_baseline.json"
CRITICAL_FILES = (
    "desktop_app.py",
    "sentinel_security/orchestrator.py",
    "workers/guardian/guardian_brain.py",
)


@dataclass
class TamperAlert:
    path: str
    kind: str
    message: str


@dataclass
class IntegrityReport:
    ok: bool
    alerts: List[TamperAlert] = field(default_factory=list)
    module_verify_ok: bool = True


def _file_hash(rel: str) -> str:
    p = ROOT / rel
    if not p.is_file():
        return ""
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_baseline() -> Dict[str, str]:
    baseline = {rel: _file_hash(rel) for rel in CRITICAL_FILES}
    SECURITY_DIR.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    build_manifest()
    return baseline


def check_integrity() -> IntegrityReport:
    report = IntegrityReport(ok=True)
    if not BASELINE_PATH.is_file():
        build_baseline()
        report.alerts.append(TamperAlert("", "baseline_created", "Integrity baseline initialized"))
        return report

    try:
        baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        report.ok = False
        report.alerts.append(TamperAlert(str(BASELINE_PATH), "corrupt_baseline", "Baseline file corrupt"))
        return report

    for rel, expected in baseline.items():
        current = _file_hash(rel)
        if not current:
            report.ok = False
            report.alerts.append(TamperAlert(rel, "missing", "Critical file missing"))
        elif current != expected:
            report.ok = False
            report.alerts.append(TamperAlert(rel, "modified", "Hash mismatch vs baseline"))

    mod_results = verify_all()
    if any(not r.ok for r in mod_results):
        report.module_verify_ok = False
        report.ok = False
        for r in mod_results:
            for f in r.failures[:3]:
                report.alerts.append(TamperAlert(r.module, "module_hash", f))

    return report


def restore_hint() -> str:
    return (
        "Restore from last verified copy: git checkout -- <file> or reinstall from signed release. "
        "Run: python run_security_audit.py --rebuild-baseline"
    )
