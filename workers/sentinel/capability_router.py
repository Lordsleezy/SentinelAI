"""
SentinelCapabilityRouter — single entry for chat intent → internal engine.

User-facing: always Sentinel.
Internal: guardian | forge | earn | earn_research | memory | market | home | learning | general

This is a thin facade over :mod:`workers.sentinel.unified_router`. All
keyword lists live there; this module only adds the post-classification
"promote to learning engine when the message reads like an unknown
capability request" rule.
"""
from __future__ import annotations

from dataclasses import dataclass

from workers.sentinel.unified_router import (
    RouteDecision,
    classify_intent,
    looks_like_unknown_task,
)


@dataclass
class SentinelCapabilityRouter:
    """Facade over unified_router with a learning-engine promotion."""

    @staticmethod
    def route(message: str) -> RouteDecision:
        lower = (message or "").lower().strip()
        decision = classify_intent(message)
        if decision.internal_engine == "general" and looks_like_unknown_task(lower):
            return RouteDecision(
                "learning", 0.55, execute=True, reason="unknown capability",
            )
        return decision


def route_message(message: str) -> RouteDecision:
    return SentinelCapabilityRouter.route(message)
