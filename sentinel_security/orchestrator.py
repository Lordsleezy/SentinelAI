"""Security orchestrator — wires all layers without UI changes."""
from __future__ import annotations

import logging
from functools import wraps
from typing import Any, Callable, Dict, Optional

from sentinel_security.ai_safety import SafetyVerdict, analyze_text, check_tool_invocation
from sentinel_security.audit_log import ImmutableAuditLog
from sentinel_security.config import CLOUD_SYNC_ENABLED
from sentinel_security.guardian_internal_audit import run_internal_audit
from sentinel_security.local_first import audit_local_first, audit_summary_dict
from sentinel_security.module_signing import build_manifest, verify_all
from sentinel_security.pqc import pqc_status
from sentinel_security.secrets_store import SecretsStore
from sentinel_security.self_protection import build_baseline, check_integrity
from sentinel_security.vault_crypto import vault_status
from sentinel_security.zero_trust import ZeroTrustPolicy, PermissionDenied

logger = logging.getLogger("sentinel.security")

_instance: Optional["SecurityOrchestrator"] = None


class SecurityOrchestrator:
    def __init__(self) -> None:
        self.audit = ImmutableAuditLog()
        self.zero_trust = ZeroTrustPolicy()
        self.secrets = SecretsStore()
        self.audit.record("security_stack_initialized", module="shield", detail={
            "cloud_sync": CLOUD_SYNC_ENABLED,
        })

    def bootstrap(self) -> Dict[str, Any]:
        """Startup: integrity check, manifest, baseline."""
        integrity = check_integrity()
        if not integrity.ok:
            for a in integrity.alerts:
                logger.warning("[SECURITY] %s %s: %s", a.kind, a.path, a.message)
            self.audit.record("integrity_alert", module="shield", detail={
                "alerts": [{"path": a.path, "kind": a.kind} for a in integrity.alerts[:10]],
            })
        else:
            self.audit.record("integrity_ok", module="shield")

        local = audit_local_first()
        self.audit.record("local_first_audit", module="shield", detail=audit_summary_dict())

        return {
            "integrity_ok": integrity.ok,
            "local_first_passed": local.passed,
            "cloud_sync_enabled": CLOUD_SYNC_ENABLED,
            "vault": vault_status(),
            "pqc": pqc_status().__dict__,
            "secrets_backend": self.secrets.backends_supported(),
        }

    def gate_request(self, module: str, permission: str, message: str = "") -> Optional[SafetyVerdict]:
        """Returns verdict if blocked; None if allowed."""
        try:
            self.zero_trust.require(module, permission)
        except PermissionDenied as e:
            self.audit.record("permission_denied", module=module, detail={
                "permission": e.permission,
            })
            v = SafetyVerdict(allowed=False, blocked=True, reasons=[str(e)], risk_level="high")
            return v
        if message:
            verdict = analyze_text(message)
            if verdict.blocked:
                self.audit.record("ai_safety_block", module=module, detail={"reasons": verdict.reasons})
                return verdict
        return None

    def gate_tool(self, module: str, tool: str, args: str, message: str = "") -> Optional[SafetyVerdict]:
        try:
            self.zero_trust.require(module, "network")
        except PermissionDenied as e:
            return SafetyVerdict(allowed=False, blocked=True, reasons=[str(e)])
        verdict = check_tool_invocation(module, tool, args, message)
        if verdict.blocked:
            self.audit.record("tool_execution_blocked", module=module, target=tool, detail={
                "reasons": verdict.reasons,
                "args_preview": args[:200],
            })
            return verdict
        self.audit.record("tool_execution", module=module, target=tool, detail={"args_preview": args[:200]})
        return None

    def record_credential_change(self, action: str, name: str) -> None:
        self.audit.record("credential_change", module="shield", detail={"action": action, "name": name})

    def record_file_delete(self, path: str, module: str = "system") -> None:
        self.audit.record("file_delete", module=module, target=path)

    def full_audit_report(self) -> Dict[str, Any]:
        health = run_internal_audit()
        return {
            "bootstrap": self.bootstrap(),
            "local_first": audit_summary_dict(),
            "zero_trust": self.zero_trust.snapshot(),
            "module_verify": [{"module": r.module, "ok": r.ok, "failures": r.failures} for r in verify_all()],
            "audit_chain_valid": self.audit.verify_chain(),
            "health": {
                "score": health.score,
                "findings": [{"category": f.category, "severity": f.severity, "summary": f.summary} for f in health.findings],
                "open_ports_count": len(health.open_ports),
            },
            "health_markdown": health.to_markdown(),
        }


def get_security() -> SecurityOrchestrator:
    global _instance
    if _instance is None:
        _instance = SecurityOrchestrator()
    return _instance


def security_middleware(module: str, permission: str = "network"):
    """Decorator for Flask handlers — no UI impact."""

    def decorator(fn: Callable):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            sec = get_security()
            msg = ""
            try:
                from flask import request
                data = request.get_json(silent=True) or {}
                msg = str(data.get("message") or data.get("text") or "")
            except Exception:
                pass
            blocked = sec.gate_request(module, permission, msg)
            if blocked:
                return {
                    "status": "blocked",
                    "error": "Security policy blocked this request",
                    "reasons": blocked.reasons,
                }, 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator
