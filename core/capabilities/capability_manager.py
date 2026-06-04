"""
Capability Manager — ensure dependencies before any Sentinel task.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from core.capabilities.capability_registry import (
    InstallTier,
    capability_ids_for_build_type,
    capabilities_for_domain,
)
from core.capabilities.runtime_installer import install_capability
from core.capabilities.runtime_validator import ValidationResult, validate_capability

logger = logging.getLogger("sentinel.capabilities")

_manager: Optional["CapabilityManager"] = None

ProgressFn = Optional[Callable[[int, str], None]]
LogFn = Optional[Callable[[str, str], None]]


class CapabilityManager:
    """Check → install → verify capabilities for a domain or build type."""

    def __init__(self, socketio: Any = None):
        self.socketio = socketio

    def _emit(self, event: str, payload: Dict[str, Any]) -> None:
        if self.socketio:
            try:
                self.socketio.emit(event, payload)
            except Exception:
                pass

    def validate_ids(self, capability_ids: List[str]) -> List[ValidationResult]:
        return [validate_capability(cid) for cid in capability_ids]

    def status_for_domain(self, domain: str) -> Dict[str, Any]:
        specs = capabilities_for_domain(domain)
        caps = []
        all_ok = True
        for spec in specs:
            v = validate_capability(spec.id)
            caps.append({
                "id": spec.id,
                "label": spec.label,
                "tier": int(spec.tier),
                "dependencies": list(spec.dependencies or []),
                "installed": v.installed,
                "healthy": v.healthy,
                "version": v.version,
                "message": v.message,
                "path": v.path,
                "last_verified": v.last_verified,
                "verification_status": "verified" if (v.installed and v.healthy) else "missing",
            })
            if not v.installed:
                all_ok = False
        return {
            "domain": domain.upper(),
            "ready": all_ok,
            "capabilities": caps,
        }

    def builder_status_panels(self) -> List[Dict[str, Any]]:
        """Status center rows: GAME, WEB, DESKTOP, ANDROID, GUARDIAN, AI."""
        panels = []
        for domain, title in (
            ("GAME", "GAME"),
            ("WEB", "WEB"),
            ("DESKTOP", "DESKTOP"),
            ("ANDROID", "ANDROID"),
            ("GUARDIAN", "GUARDIAN"),
            ("AI", "AI"),
            ("EARN", "EARN"),
            ("RESEARCH", "RESEARCH"),
            ("VISION", "VISION"),
        ):
            st = self.status_for_domain(domain)
            lines = []
            for c in st["capabilities"]:
                ok = c["installed"] and c["healthy"]
                ver = f" ({c['version']})" if c.get("version") else ""
                lines.append({
                    "label": c["label"],
                    "ok": ok,
                    "status_line": f"{'✓' if ok else '✗'} {c['label']}{ver}",
                    "version": c.get("version", ""),
                    "last_verified": c.get("last_verified", ""),
                })
            panels.append({
                "type": domain,
                "title": title,
                "ready": st["ready"],
                "lines": lines,
                "capabilities": st["capabilities"],
            })
        return panels

    def ensure_for_build_type(
        self,
        build_type_value: str,
        *,
        auto_install: bool = True,
        on_progress: ProgressFn = None,
        log_fn: LogFn = None,
    ) -> Dict[str, Any]:
        """Ensure capabilities for a forge build. Returns {ok, missing, installed, errors}."""
        ids = capability_ids_for_build_type(build_type_value)
        return self.ensure_capabilities(
            ids, auto_install=auto_install, on_progress=on_progress, log_fn=log_fn,
        )

    def ensure_capabilities(
        self,
        capability_ids: List[str],
        *,
        auto_install: bool = True,
        on_progress: ProgressFn = None,
        log_fn: LogFn = None,
    ) -> Dict[str, Any]:
        missing: List[str] = []
        installed: List[str] = []
        errors: List[str] = []

        for i, cid in enumerate(capability_ids):
            if on_progress:
                pct = 5 + int(15 * (i + 1) / max(len(capability_ids), 1))
                on_progress(pct, f"Checking {cid}")

            v = validate_capability(cid)
            if v.installed and v.healthy:
                continue
            missing.append(cid)
            if not auto_install:
                errors.append(f"{cid}: not installed")
                continue

            if on_progress:
                on_progress(12, f"Installing {cid}")
            self._emit("capability_install", {"id": cid, "phase": "installing"})
            if log_fn:
                log_fn(f"Installing capability: {cid}", "info")

            result = install_capability(cid, log_fn=log_fn)
            if result.get("ok") or result.get("skipped"):
                v2 = validate_capability(cid)
                if v2.installed:
                    installed.append(cid)
                    self._emit("capability_install", {"id": cid, "phase": "ready", "path": v2.path})
                else:
                    errors.append(f"{cid}: install reported ok but still missing")
            else:
                err = result.get("error", "install failed")
                errors.append(f"{cid}: {err}")
                self._emit("capability_install", {"id": cid, "phase": "failed", "error": err})

        ok = len(errors) == 0 and len(missing) <= len(installed)
        if not auto_install and missing:
            ok = False
        return {
            "ok": ok and not errors,
            "missing": [m for m in missing if m not in installed],
            "installed": installed,
            "errors": errors,
        }

    def bootstrap_tier2(self, log_fn: LogFn = None) -> None:
        """First-launch installs for Tier 2 capabilities (Godot, Playwright, …)."""
        from core.capabilities.capability_registry import CAPABILITIES, InstallTier
        tier2 = [s.id for s in CAPABILITIES.values() if s.tier == InstallTier.RECOMMENDED]
        self.ensure_capabilities(tier2[:4], auto_install=True, log_fn=log_fn)


def get_capability_manager(socketio: Any = None) -> CapabilityManager:
    global _manager
    if _manager is None or (socketio and _manager.socketio is None):
        _manager = CapabilityManager(socketio)
    elif socketio:
        _manager.socketio = socketio
    return _manager
