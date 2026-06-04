"""Failure classification for autonomous repair."""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class FailureClass(str, Enum):
    AUTH_FAILURE = "auth_failure"
    NETWORK_FAILURE = "network_failure"
    PROVIDER_FAILURE = "provider_failure"
    MISSING_DEPENDENCY = "missing_dependency"
    MISSING_ENV_VAR = "missing_environment_variable"
    SCHEMA_FAILURE = "schema_failure"
    DEPLOYMENT_FAILURE = "deployment_failure"
    BROWSER_FAILURE = "browser_failure"
    RATE_LIMIT = "rate_limit"
    APPROVAL_BLOCKED = "approval_blocked"
    UNKNOWN = "unknown"


@dataclass
class FailureClassification:
    failure_class: FailureClass
    signature: str
    confidence: float
    hints: list

    def to_dict(self) -> Dict[str, Any]:
        return {
            "failure_class": self.failure_class.value,
            "signature": self.signature,
            "confidence": self.confidence,
            "hints": self.hints,
        }


def classify_failure(
    error: str,
    context: Optional[Dict[str, Any]] = None,
) -> FailureClassification:
    ctx = context or {}
    lower = (error or "").lower()
    stderr = (ctx.get("terminal_stderr") or ctx.get("stderr") or "").lower()
    combined = f"{lower} {stderr}"

    rules = [
        (FailureClass.AUTH_FAILURE, (
            "unauthorized", "401", "403", "authentication", "invalid api key",
            "access denied", "login required", "jwt", "oauth",
        )),
        (FailureClass.NETWORK_FAILURE, (
            "connection refused", "timeout", "timed out", "dns", "network",
            "econnrefused", "unreachable", "ssl", "certificate",
        )),
        (FailureClass.MISSING_DEPENDENCY, (
            "playwright", "not installed", "modulenotfound", "no module named",
            "import error", "pyautogui",
        )),
        (FailureClass.MISSING_ENV_VAR, (
            "environment variable", "env var", "not configured", "missing key",
            "supabase_url", "stripe_secret", "api key required",
        )),
        (FailureClass.SCHEMA_FAILURE, (
            "policy already exists", "relation does not exist", "syntax error",
            "migration failed", "duplicate key", "constraint", "sql",
        )),
        (FailureClass.DEPLOYMENT_FAILURE, (
            "deploy failed", "build failed", "netlify", "vercel", "github actions",
        )),
        (FailureClass.BROWSER_FAILURE, (
            "selector", "element not found", "playwright", "navigation failed",
            "page.goto", "timeout waiting for",
        )),
        (FailureClass.RATE_LIMIT, (
            "rate limit", "429", "too many requests", "throttl",
        )),
        (FailureClass.PROVIDER_FAILURE, (
            "provider", "api error", "500", "502", "503", "bad gateway",
        )),
        (FailureClass.APPROVAL_BLOCKED, (
            "approval", "rejected", "awaiting_approval",
        )),
    ]

    for fclass, keywords in rules:
        hits = [k for k in keywords if k in combined]
        if hits:
            sig = _normalize_signature(combined, hits[0])
            return FailureClassification(
                failure_class=fclass,
                signature=sig,
                confidence=min(0.95, 0.5 + 0.1 * len(hits)),
                hints=hits[:5],
            )

    sig = _normalize_signature(combined, "unknown")
    return FailureClassification(
        failure_class=FailureClass.UNKNOWN,
        signature=sig,
        confidence=0.3,
        hints=[],
    )


def _normalize_signature(text: str, anchor: str) -> str:
    snippet = text[:400]
    snippet = re.sub(r"\d{4,}", "#", snippet)
    snippet = re.sub(r"[a-f0-9]{8,}", "hash", snippet)
    return f"{anchor}:{snippet[:120]}"
