"""Verification engine — confirm task outcomes."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from core.sentinelvision.providers.registry import get_provider

logger = logging.getLogger("sentinel.vision.verify")


class VerificationEngine:
    def verify_goal(
        self,
        objective: str,
        provider_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ctx = context or {}
        if ctx.get("autonomous"):
            from core.sentinelvision.providers.workflows import get_workflow_runner
            result = get_workflow_runner().verify_autonomous(provider_id, objective, ctx)
            if result.get("checks"):
                return result

        provider = get_provider(provider_id)
        if provider:
            result = provider.verify(objective, ctx)
            result["provider_id"] = provider_id
            return result
        return {"ok": False, "verified": False, "message": f"unknown provider: {provider_id}"}
