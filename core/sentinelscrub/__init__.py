"""
Backward compatibility — SentinelScrub merged into Sentinel Vision.

Use: from core.sentinelvision import get_vision_engine
"""
from core.sentinelvision import (
    SentinelVisionEngine,
    get_vision_engine,
    get_scrub_engine,
)
from core.sentinelvision import SentinelVisionEngine as SentinelScrubEngine

__all__ = [
    "SentinelVisionEngine",
    "SentinelScrubEngine",
    "get_vision_engine",
    "get_scrub_engine",
]
