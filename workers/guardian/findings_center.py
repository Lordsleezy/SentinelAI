"""
Guardian Findings Center — structured session findings under memory/vault/findings/.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from workers.guardian.bundled_toolchain import get_sentinel_root

_VAULT = Path("memory") / "vault" / "findings"
_INDEX = "sessions_index.json"


def _root() -> Path:
    p = get_sentinel_root() / _VAULT
    p.mkdir(parents=True, exist_ok=True)
    return p


def _session_dir(session_id: str) -> Path:
    safe = re.sub(r"[^\w\-]", "_", session_id)[:80]
    d = _root() / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_index() -> Dict[str, Any]:
    idx = _root() / _INDEX
    if idx.is_file():
        try:
            return json.loads(idx.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"sessions": []}


def _save_index(data: Dict[str, Any]) -> None:
    (_root() / _INDEX).write_text(json.dumps(data, indent=2), encoding="utf-8")


def start_session(target: str, session_id: Optional[str] = None) -> Dict[str, Any]:
    sid = session_id or f"guardian-{uuid.uuid4().hex[:12]}"
    meta = {
        "session_id": sid,
        "target": target,
        "started_at": datetime.now().isoformat(),
        "hosts": [],
        "ports": [],
        "technologies": [],
        "endpoints": [],
        "screenshots": [],
        "findings": [],
    }
    d = _session_dir(sid)
    (d / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    idx = _load_index()
    sessions = idx.setdefault("sessions", [])
    sessions = [s for s in sessions if s.get("session_id") != sid]
    sessions.insert(0, {"session_id": sid, "target": target, "started_at": meta["started_at"]})
    idx["sessions"] = sessions[:100]
    _save_index(idx)
    return meta


def _load_meta(session_id: str) -> Dict[str, Any]:
    p = _session_dir(session_id) / "meta.json"
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    return start_session("unknown", session_id)


def _save_meta(session_id: str, meta: Dict[str, Any]) -> None:
    (_session_dir(session_id) / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def add_hosts(session_id: str, hosts: List[str]) -> None:
    meta = _load_meta(session_id)
    seen = set(meta.get("hosts") or [])
    for h in hosts:
        if h and h not in seen:
            seen.add(h)
            meta.setdefault("hosts", []).append(h)
    _save_meta(session_id, meta)


def add_ports(session_id: str, ports: List[Dict[str, Any]]) -> None:
    meta = _load_meta(session_id)
    meta.setdefault("ports", []).extend(ports)
    _save_meta(session_id, meta)


def add_technologies(session_id: str, techs: List[str]) -> None:
    meta = _load_meta(session_id)
    seen = set(meta.get("technologies") or [])
    for t in techs:
        if t and t not in seen:
            seen.add(t)
            meta.setdefault("technologies", []).append(t)
    _save_meta(session_id, meta)


def add_endpoints(session_id: str, endpoints: List[str]) -> None:
    meta = _load_meta(session_id)
    seen = set(meta.get("endpoints") or [])
    for e in endpoints:
        if e and e not in seen:
            seen.add(e)
            meta.setdefault("endpoints", []).append(e)
    _save_meta(session_id, meta)


def add_finding(
    session_id: str,
    *,
    title: str,
    severity: str = "informational",
    confidence: str = "medium",
    evidence: str = "",
    tool_source: str = "guardian",
    discovery_path: str = "",
    ai_explanation: str = "",
) -> Dict[str, Any]:
    sev = severity.lower()
    if sev not in ("informational", "low", "medium", "high", "critical"):
        sev = "informational"
    finding = {
        "id": f"find_{uuid.uuid4().hex[:8]}",
        "title": title,
        "severity": sev,
        "confidence": confidence,
        "evidence": evidence[:8000],
        "tool_source": tool_source,
        "discovery_path": discovery_path,
        "ai_explanation": ai_explanation[:4000],
        "created_at": datetime.now().isoformat(),
    }
    meta = _load_meta(session_id)
    meta.setdefault("findings", []).append(finding)
    _save_meta(session_id, meta)
    (_session_dir(session_id) / "findings").mkdir(exist_ok=True)
    (_session_dir(session_id) / "findings" / f"{finding['id']}.json").write_text(
        json.dumps(finding, indent=2), encoding="utf-8",
    )
    return finding


def get_session(session_id: str) -> Dict[str, Any]:
    return _load_meta(session_id)


def list_sessions(limit: int = 30) -> List[Dict[str, Any]]:
    return (_load_index().get("sessions") or [])[:limit]


def export_center(session_id: str) -> Dict[str, Any]:
    return get_session(session_id)
