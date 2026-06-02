"""Layer 2 — Zero-trust module isolation and explicit permissions."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from sentinel_security.config import POLICY_PATH, SECURITY_DIR

logger = logging.getLogger("sentinel.security.zero_trust")

PERMISSIONS = ("filesystem", "network", "browser", "email", "ssh", "credentials")

DEFAULT_POLICY: Dict[str, Dict[str, bool]] = {
    "guardian": {"filesystem": True, "network": True, "browser": False, "email": False, "ssh": False, "credentials": False},
    "earn": {"filesystem": True, "network": True, "browser": False, "email": False, "ssh": False, "credentials": False},
    "forge": {"filesystem": True, "network": False, "browser": False, "email": False, "ssh": False, "credentials": False},
    "vision": {"filesystem": True, "network": False, "browser": False, "email": False, "ssh": False, "credentials": False},
    "memory": {"filesystem": True, "network": False, "browser": False, "email": False, "ssh": False, "credentials": False},
    "shield": {"filesystem": True, "network": True, "browser": False, "email": False, "ssh": False, "credentials": True},
    "sync": {"filesystem": True, "network": True, "browser": True, "email": False, "ssh": False, "credentials": False},
}


@dataclass
class PermissionDenied(Exception):
    module: str
    permission: str
    reason: str = "not granted"


class ZeroTrustPolicy:
    def __init__(self) -> None:
        SECURITY_DIR.mkdir(parents=True, exist_ok=True)
        self._policy = self._load()

    def _load(self) -> Dict[str, Dict[str, bool]]:
        if POLICY_PATH.is_file():
            try:
                data = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                logger.warning("Invalid module policy — using defaults")
        self._save(DEFAULT_POLICY)
        return dict(DEFAULT_POLICY)

    def _save(self, policy: Dict) -> None:
        POLICY_PATH.write_text(json.dumps(policy, indent=2), encoding="utf-8")

    def check(self, module: str, permission: str) -> bool:
        if permission not in PERMISSIONS:
            return False
        mod = self._policy.get(module, {})
        return bool(mod.get(permission, False))

    def require(self, module: str, permission: str) -> None:
        if not self.check(module, permission):
            raise PermissionDenied(module, permission)

    def grant(self, module: str, permission: str, enabled: bool = True) -> None:
        if permission not in PERMISSIONS:
            return
        self._policy.setdefault(module, {p: False for p in PERMISSIONS})
        self._policy[module][permission] = enabled
        self._save(self._policy)

    def snapshot(self) -> Dict[str, Dict[str, bool]]:
        return dict(self._policy)
