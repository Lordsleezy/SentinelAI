"""Layer 9 — Immutable append-only audit log with hash chain."""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sentinel_security.config import AUDIT_LOG_PATH, SECURITY_DIR

logger = logging.getLogger("sentinel.security.audit")

_lock = threading.Lock()
_GENESIS = "0" * 64


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_entry(prev: str, payload: str) -> str:
    return hashlib.sha256(f"{prev}|{payload}".encode("utf-8")).hexdigest()


class ImmutableAuditLog:
    def __init__(self, path: Path = AUDIT_LOG_PATH) -> None:
        SECURITY_DIR.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._last_hash = _GENESIS
        if self.path.is_file():
            self._last_hash = self._read_last_hash()

    def _read_last_hash(self) -> str:
        try:
            lines = self.path.read_text(encoding="utf-8").strip().splitlines()
            if not lines:
                return _GENESIS
            last = json.loads(lines[-1])
            return last.get("chain_hash", _GENESIS)
        except Exception:
            return _GENESIS

    def record(
        self,
        event_type: str,
        *,
        module: str = "system",
        actor: str = "local",
        detail: Optional[Dict[str, Any]] = None,
        target: str = "",
    ) -> Dict[str, Any]:
        entry = {
            "ts": _utc_now(),
            "event_type": event_type,
            "module": module,
            "actor": actor,
            "target": target,
            "detail": detail or {},
        }
        payload = json.dumps(entry, sort_keys=True)
        with _lock:
            entry["prev_hash"] = self._last_hash
            entry["chain_hash"] = _hash_entry(self._last_hash, payload)
            self._last_hash = entry["chain_hash"]
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        return entry

    def search(
        self,
        *,
        event_type: Optional[str] = None,
        module: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        if not self.path.is_file():
            return []
        out: List[Dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event_type and e.get("event_type") != event_type:
                continue
            if module and e.get("module") != module:
                continue
            out.append(e)
        return out[-limit:]

    def verify_chain(self) -> bool:
        prev = _GENESIS
        if not self.path.is_file():
            return True
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            payload = json.dumps(
                {k: e[k] for k in ("ts", "event_type", "module", "actor", "target", "detail")},
                sort_keys=True,
            )
            expected = _hash_entry(prev, payload)
            if e.get("chain_hash") != expected:
                return False
            prev = e.get("chain_hash", _GENESIS)
        return True
