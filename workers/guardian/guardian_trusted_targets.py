"""
Persisted trusted targets for Guardian — avoids repeated authorization prompts.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_STORE = Path(__file__).resolve().parents[2] / "memory" / "vault" / "guardian_trusted_targets.json"
_DEFAULT_TTL_DAYS = 365


def _load() -> Dict[str, Any]:
    if _STORE.is_file():
        try:
            return json.loads(_STORE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("trusted targets load failed: %s", e)
    return {"targets": {}, "settings": {"default_ttl_days": _DEFAULT_TTL_DAYS}}


def _save(data: Dict[str, Any]) -> None:
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    _STORE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _normalize(target: str) -> str:
    t = (target or "").strip().lower()
    if t.startswith("http://"):
        t = t[7:]
    if t.startswith("https://"):
        t = t[8:]
    return t.rstrip("/").split("/")[0]


def is_trusted(target: str) -> bool:
    key = _normalize(target)
    if not key:
        return False
    data = _load()
    entry = (data.get("targets") or {}).get(key)
    if not entry or not entry.get("approved"):
        return False
    exp = entry.get("expires_at")
    if exp:
        try:
            if datetime.fromisoformat(exp) < datetime.now():
                return False
        except ValueError:
            pass
    return True


def approve(target: str, *, ttl_days: Optional[int] = None, note: str = "") -> Dict[str, Any]:
    key = _normalize(target)
    data = _load()
    ttl = ttl_days if ttl_days is not None else int(
        (data.get("settings") or {}).get("default_ttl_days", _DEFAULT_TTL_DAYS)
    )
    expires = None
    if ttl > 0:
        expires = (datetime.now() + timedelta(days=ttl)).isoformat()
    data.setdefault("targets", {})[key] = {
        "approved": True,
        "added_at": datetime.now().isoformat(),
        "expires_at": expires,
        "note": note,
        "display": target.strip(),
    }
    _save(data)
    logger.info("[GUARDIAN] Trusted target approved: %s", key)
    return data["targets"][key]


def revoke(target: str) -> bool:
    key = _normalize(target)
    data = _load()
    targets = data.get("targets") or {}
    if key in targets:
        del targets[key]
        _save(data)
        return True
    return False


def list_trusted() -> List[Dict[str, Any]]:
    data = _load()
    out = []
    for key, entry in sorted((data.get("targets") or {}).items()):
        out.append({"target": key, **entry})
    return out


def get_settings() -> Dict[str, Any]:
    return _load().get("settings") or {"default_ttl_days": _DEFAULT_TTL_DAYS}


def reset_all() -> None:
    _save({"targets": {}, "settings": {"default_ttl_days": _DEFAULT_TTL_DAYS}})
