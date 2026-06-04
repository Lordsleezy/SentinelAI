"""Sentinel Vision workflow memory — reuse successful patterns."""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.sentinelvision.types import utc_now

logger = logging.getLogger("sentinel.vision.memory")

_ROOT = Path(__file__).resolve().parents[3]
_STORE = _ROOT / "data" / "sentinelvision" / "workflow_memory.json"
_lock = threading.Lock()


def _load() -> Dict[str, Any]:
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    if not _STORE.is_file():
        return {"workflows": [], "preferences": {}, "provider_configs": {}}
    try:
        return json.loads(_STORE.read_text(encoding="utf-8"))
    except Exception:
        return {"workflows": [], "preferences": {}, "provider_configs": {}}


def _save(data: Dict[str, Any]) -> None:
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    _STORE.write_text(json.dumps(data, indent=2), encoding="utf-8")


class VisionMemory:
    def record_workflow(
        self,
        provider_id: str,
        objective: str,
        *,
        success: bool,
        plan_summary: str,
        research_summary: str = "",
    ) -> None:
        with _lock:
            data = _load()
            workflows = data.setdefault("workflows", [])
            workflows.append({
                "provider_id": provider_id,
                "objective": objective[:500],
                "success": success,
                "plan_summary": plan_summary[:2000],
                "research_summary": research_summary[:2000],
                "timestamp": utc_now(),
            })
            data["workflows"] = workflows[-200:]
            _save(data)

    def find_similar(self, objective: str, limit: int = 5) -> List[Dict[str, Any]]:
        lower = objective.lower()
        tokens = set(lower.split())
        with _lock:
            workflows = _load().get("workflows", [])
        scored = []
        for w in workflows:
            if not w.get("success"):
                continue
            obj = (w.get("objective") or "").lower()
            overlap = len(tokens & set(obj.split()))
            if overlap > 0:
                scored.append((overlap, w))
        scored.sort(key=lambda x: -x[0])
        return [w for _, w in scored[:limit]]

    def set_preference(self, key: str, value: Any) -> None:
        with _lock:
            data = _load()
            data.setdefault("preferences", {})[key] = value
            _save(data)

    def get_preferences(self) -> Dict[str, Any]:
        return _load().get("preferences", {})

    def set_provider_config(self, provider_id: str, config: Dict[str, Any]) -> None:
        with _lock:
            data = _load()
            data.setdefault("provider_configs", {})[provider_id] = config
            _save(data)

    def get_provider_config(self, provider_id: str) -> Dict[str, Any]:
        return _load().get("provider_configs", {}).get(provider_id, {})
