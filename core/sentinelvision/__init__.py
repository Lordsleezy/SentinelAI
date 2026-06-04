"""
Sentinel Vision — visual understanding, browser/desktop/provider operation,
research, verification, and autonomous repair for Sentinel AI.
"""
from core.sentinelvision.engine import SentinelVisionEngine

__all__ = ["SentinelVisionEngine", "get_vision_engine", "get_scrub_engine"]

_engine: SentinelVisionEngine | None = None


def get_vision_engine(socketio=None) -> SentinelVisionEngine:
    global _engine
    if _engine is None:
        _engine = SentinelVisionEngine(socketio=socketio)
    elif socketio and _engine.socketio is None:
        _engine.socketio = socketio
    return _engine


def get_scrub_engine(socketio=None) -> SentinelVisionEngine:
    """Backward compatibility alias."""
    return get_vision_engine(socketio=socketio)


SentinelScrubEngine = SentinelVisionEngine
