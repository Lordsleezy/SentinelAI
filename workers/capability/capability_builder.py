"""
Capability Builder — requests Forge to generate a missing tool.

Minimal implementation. The actual build is performed by the Forge worker; this
module only formats the request and records the build in the registry.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from .registry import register_capability

logger = logging.getLogger(__name__)


def request_build(spec: Dict[str, Any], approved: bool = False) -> Dict[str, Any]:
    """Request a Forge build for ``spec``. Returns a structured result dict.

    ``spec`` should contain at least ``name`` and ``description``. Build is
    gated by ``approved`` so no Forge run kicks off without user consent.
    """
    name = spec.get("name") or "unnamed_capability"
    if not approved:
        return {"status": "denied", "name": name,
                "message": "Forge build requires explicit approval"}
    register_capability(name, {"provider": "forge", "status": "pending", "spec": spec})
    logger.info("Capability '%s' queued for Forge build", name)
    return {"status": "queued", "name": name}
