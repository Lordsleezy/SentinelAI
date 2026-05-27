"""Runtime model router for SentinelAI."""

from typing import Dict

import db
from capability_registry import CapabilityRegistry
from routing_policies import DefaultRoutingPolicy


class ModelRouter:
    def __init__(self):
        self.registry = CapabilityRegistry()
        self.policy = DefaultRoutingPolicy()

    def route(self, task_type: str, prompt: str, prefer_local: bool = True) -> Dict:
        selection = self.policy.choose(self.registry, task_type, prompt, prefer_local)
        db.log_event("model_routed", f"{task_type}->{selection.get('id')}:{selection.get('model')}")
        return selection

    def status(self) -> Dict:
        return {"models": self.registry.list_models()}


_router = None


def get_model_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router
