"""Layer 1 — Local-first audit: detect silent external uploads."""
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from sentinel_security.config import CLOUD_SYNC_ENABLED, ROOT

logger = logging.getLogger("sentinel.security.local_first")

MODULE_DIRS = {
    "guardian": ROOT / "workers" / "guardian",
    "earn": ROOT / "workers" / "earn",
    "forge": ROOT / "builders",
    "vision": ROOT / "workers" / "home",
    "memory": ROOT / "workers" / "memory",
}

# HTTP upload / external POST patterns (static scan)
_UPLOAD_HINTS = ("upload", "put_object", "send_file", "multipart")
_EXTERNAL_LIBS = ("requests.post", "requests.put", "httpx.post", "httpx.put", "urllib.request.urlopen")
_OPT_IN_MARKERS = ("CLOUD_SYNC", "cloud_sync", "explicit_upload", "SENTINEL_CLOUD_SYNC")


@dataclass
class ModuleAuditResult:
    module: str
    files_scanned: int
    external_calls: List[str] = field(default_factory=list)
    upload_hints: List[str] = field(default_factory=list)
    silent_risk: bool = False
    notes: List[str] = field(default_factory=list)


@dataclass
class LocalFirstReport:
    cloud_sync_enabled: bool
    modules: List[ModuleAuditResult] = field(default_factory=list)
    sync_modules_found: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        if self.cloud_sync_enabled:
            return True
        for m in self.modules:
            if m.silent_risk:
                return False
        return True


def _scan_file(path: Path) -> tuple[List[str], List[str]]:
    external: List[str] = []
    uploads: List[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return external, uploads
    if any(m in text for m in _OPT_IN_MARKERS):
        return external, uploads
    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        for hint in _EXTERNAL_LIBS:
            if hint in stripped and "localhost" not in stripped and "127.0.0.1" not in stripped:
                external.append(f"{path.name}:{line_no} {hint}")
        low = stripped.lower()
        if any(u in low for u in _UPLOAD_HINTS) and ("http" in low or "post" in low):
            uploads.append(f"{path.name}:{line_no}")
    return external[:20], uploads[:10]


def audit_module(name: str, base: Path) -> ModuleAuditResult:
    result = ModuleAuditResult(module=name, files_scanned=0)
    if not base.is_dir():
        result.notes.append("path missing")
        return result
    for py in base.rglob("*.py"):
        if "__pycache__" in py.parts or "test" in py.name:
            continue
        result.files_scanned += 1
        ext, up = _scan_file(py)
        result.external_calls.extend(ext)
        result.upload_hints.extend(up)
    # Risk: silent upload / exfil only (GET to public APIs e.g. bounty-targets is expected)
    post_calls = [c for c in result.external_calls if ".post" in c.lower() or ".put" in c.lower()]
    result.silent_risk = bool(result.upload_hints or post_calls) and not CLOUD_SYNC_ENABLED
    if post_calls:
        result.notes.append("external POST/PUT detected — enable SENTINEL_CLOUD_SYNC to allow cloud upload")
    elif result.external_calls:
        result.notes.append("external HTTP (mostly read) — no upload patterns")
    return result


def audit_local_first() -> LocalFirstReport:
    report = LocalFirstReport(cloud_sync_enabled=CLOUD_SYNC_ENABLED)
    for name, path in MODULE_DIRS.items():
        if not path.is_dir():
            r = ModuleAuditResult(module=name, files_scanned=0)
            r.notes.append("module path not present — skipped")
            report.modules.append(r)
            continue
        report.modules.append(audit_module(name, path))
    sync_path = ROOT / "workers" / "sync"
    if sync_path.is_dir():
        report.sync_modules_found.append("workers/sync (browser pull — not cloud upload; requires explicit sessions)")
    return report


def audit_summary_dict() -> Dict:
    r = audit_local_first()
    return {
        "cloud_sync_enabled": r.cloud_sync_enabled,
        "passed": r.passed,
        "modules": [
            {
                "module": m.module,
                "files_scanned": m.files_scanned,
                "silent_risk": m.silent_risk,
                "external_calls": m.external_calls[:5],
                "upload_hints": m.upload_hints[:5],
                "notes": m.notes,
            }
            for m in r.modules
        ],
        "sync_notes": r.sync_modules_found,
    }
