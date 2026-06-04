"""Sentinel Vision audit logging — all operator actions."""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from core.sentinelvision.types import utc_now

logger = logging.getLogger("sentinel.vision.audit")

_ROOT = Path(__file__).resolve().parents[2]
_AUDIT_PATH = _ROOT / "data" / "sentinelvision" / "audit.jsonl"
_lock = threading.Lock()


def _ensure_dir() -> None:
    _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)


def audit_log(
    event: str,
    goal_id: Optional[str] = None,
    *,
    provider_id: Optional[str] = None,
    action: Optional[str] = None,
    detail: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Append-only audit record. Never includes credential values."""
    row = {
        "timestamp": utc_now(),
        "event": event,
        "goal_id": goal_id,
        "provider_id": provider_id,
        "action": action,
        "detail": detail,
    }
    if extra:
        safe = {k: v for k, v in extra.items() if "secret" not in k.lower() and "password" not in k.lower()}
        row["extra"] = safe
    try:
        _ensure_dir()
        with _lock:
            with _AUDIT_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, default=str) + "\n")
    except Exception as e:
        logger.error("audit_log failed: %s", e)


def list_audit(limit: int = 200, goal_id: Optional[str] = None) -> list:
    if not _AUDIT_PATH.is_file():
        return []
    lines = _AUDIT_PATH.read_text(encoding="utf-8").strip().splitlines()
    rows = []
    for line in reversed(lines[-limit * 2 :]):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if goal_id and row.get("goal_id") != goal_id:
            continue
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows
