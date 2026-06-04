"""Provider interface for SentinelScrub."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class ProviderBase(ABC):
    provider_id: str = ""
    display_name: str = ""

    @abstractmethod
    def research(self, objective: str) -> Dict[str, Any]:
        """Return structured requirements — env vars, steps, URLs."""

    def login(self, vault_secrets: Dict[str, str]) -> Dict[str, Any]:
        return {"ok": False, "error": "login not implemented for this provider"}

    def execute(self, step: Dict[str, Any], operators: Any) -> Dict[str, Any]:
        return {"ok": False, "error": "execute not implemented for this provider"}

    def verify(self, objective: str, context: Dict[str, Any]) -> Dict[str, Any]:
        return {"ok": True, "verified": False, "message": "default verify — override in provider"}

    def repair(self, failure: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        return {"ok": False, "repair_plan": [], "message": "no repair strategy"}

    def match_objective(self, objective: str) -> float:
        """0–1 confidence this provider handles the objective."""
        lower = (objective or "").lower()
        keywords = getattr(self, "keywords", []) or []
        hits = sum(1 for k in keywords if k in lower)
        return min(1.0, hits / max(1, len(keywords) * 0.5)) if keywords else 0.0
