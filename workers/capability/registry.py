"""
Capability Registry — tracks installed capabilities and their providers.

Minimal implementation. Persists to `capability_registry.json` at project root.
The registry is consulted by the orchestration pipeline to decide whether a
required tool is already available locally.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "capability_registry.json"


def _registry_path() -> Path:
    return _DEFAULT_REGISTRY_PATH


def load_registry() -> Dict[str, Any]:
    """Load the capability registry from disk. Returns an empty dict on first run."""
    path = _registry_path()
    if not path.exists():
        return {"capabilities": {}}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {"capabilities": {}}
        data.setdefault("capabilities", {})
        return data
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read capability registry: %s", exc)
        return {"capabilities": {}}


def save_registry(data: Dict[str, Any]) -> bool:
    """Persist the registry to disk. Returns True on success."""
    path = _registry_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
        return True
    except OSError as exc:
        logger.warning("Failed to write capability registry: %s", exc)
        return False


def get_capability(name: str) -> Optional[Dict[str, Any]]:
    return load_registry().get("capabilities", {}).get(name)


def register_capability(name: str, info: Dict[str, Any]) -> bool:
    data = load_registry()
    data.setdefault("capabilities", {})[name] = info
    return save_registry(data)


def remove_capability(name: str) -> bool:
    data = load_registry()
    if name in data.get("capabilities", {}):
        data["capabilities"].pop(name)
        return save_registry(data)
    return False


def list_capabilities() -> Dict[str, Any]:
    return load_registry().get("capabilities", {})
