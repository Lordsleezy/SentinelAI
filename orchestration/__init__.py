"""
SentinelAI orchestration runtime package.

This layer is additive: it does not replace the existing queue, worker,
watchdog, approval, dry-run, or rollback systems.
"""

from .runtime import SentinelOrchestrator, get_orchestrator, initialize_orchestration

__all__ = ["SentinelOrchestrator", "get_orchestrator", "initialize_orchestration"]
