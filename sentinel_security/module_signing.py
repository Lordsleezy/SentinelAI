"""Layer 7 — Module signature and hash verification before load."""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from sentinel_security.config import MANIFEST_PATH, ROOT

logger = logging.getLogger("sentinel.security.signing")

SIGNED_MODULES = ("guardian", "earn", "forge", "vision", "shield")
_MODULE_PATHS = {
    "guardian": ROOT / "workers" / "guardian",
    "earn": ROOT / "workers" / "earn",
    "forge": ROOT / "builders",
    "vision": ROOT / "workers" / "vision",
    "shield": ROOT / "sentinel_security",
}


@dataclass
class VerifyResult:
    module: str
    ok: bool
    files_checked: int = 0
    failures: List[str] = field(default_factory=list)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest() -> Dict[str, Dict[str, str]]:
    manifest: Dict[str, Dict[str, str]] = {}
    for mod, base in _MODULE_PATHS.items():
        if not base.is_dir():
            continue
        manifest[mod] = {}
        for py in sorted(base.rglob("*.py")):
            if "__pycache__" in py.parts:
                continue
            rel = py.relative_to(ROOT).as_posix()
            manifest[mod][rel] = _sha256_file(py)
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def verify_module(module: str) -> VerifyResult:
    result = VerifyResult(module=module, ok=True)
    if not MANIFEST_PATH.is_file():
        result.failures.append("manifest missing — run security audit to build")
        result.ok = False
        return result
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        result.ok = False
        result.failures.append("manifest corrupt")
        return result
    expected = manifest.get(module, {})
    for rel, exp_hash in expected.items():
        path = ROOT / rel
        result.files_checked += 1
        if not path.is_file():
            result.failures.append(f"missing: {rel}")
            result.ok = False
            continue
        if _sha256_file(path) != exp_hash:
            result.failures.append(f"hash mismatch: {rel}")
            result.ok = False
    return result


def verify_all() -> List[VerifyResult]:
    if not MANIFEST_PATH.is_file():
        build_manifest()
    return [verify_module(m) for m in SIGNED_MODULES if m in _MODULE_PATHS]
