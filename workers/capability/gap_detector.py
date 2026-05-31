"""
Capability Gap Detector — identifies required tools the runtime does not have.

Minimal implementation. Real gap analysis is driven by the orchestration
pipeline; this module exposes the interface the rest of the system imports.
"""
from __future__ import annotations

import logging
from typing import Iterable, List

from .registry import list_capabilities

logger = logging.getLogger(__name__)


def detect_gaps(required: Iterable[str]) -> List[str]:
    """Return required capability names that are not present in the registry."""
    have = set(list_capabilities().keys())
    missing = [name for name in required if name not in have]
    if missing:
        logger.info("Capability gaps detected: %s", missing)
    return missing
