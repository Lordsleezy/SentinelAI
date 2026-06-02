"""Research vault persistence — memory/vault/research/ (no Memory module changes)."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from workers.earn.research.models import EvidenceItem, ResearchSession

logger = logging.getLogger("sentinel.earn.research")

ROOT = Path(__file__).resolve().parents[3] / "memory" / "vault" / "research"
SESSIONS_DIR = ROOT / "sessions"


def _session_path(session_id: str) -> Path:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    return SESSIONS_DIR / f"{session_id}.json"


def session_dir(session_id: str) -> Path:
    d = ROOT / session_id
    for sub in ("evidence", "recon", "logs", "screenshots"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def save_session(session: ResearchSession) -> None:
    _session_path(session.id).write_text(
        json.dumps(session.to_dict(), indent=2),
        encoding="utf-8",
    )


def load_session(session_id: str) -> Optional[ResearchSession]:
    p = _session_path(session_id)
    if not p.is_file():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    return ResearchSession(**{k: data[k] for k in ResearchSession.__dataclass_fields__ if k in data})


def list_sessions(limit: int = 50) -> List[Dict[str, Any]]:
    if not SESSIONS_DIR.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for p in sorted(SESSIONS_DIR.glob("res_*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append({
                "id": d.get("id"),
                "program_handle": d.get("program_handle"),
                "program_title": d.get("program_title"),
                "status": d.get("status"),
                "created_at": d.get("created_at"),
                "findings_count": len(d.get("potential_findings") or []),
                "evidence_count": len(d.get("evidence") or []),
                "targets_count": len(d.get("targets_probed") or []),
            })
        except Exception:
            continue
    return out


def append_log(session: ResearchSession, msg: str) -> None:
    session.logs.append(msg)
    save_session(session)


def save_recon_artifact(session_id: str, tool: str, content: str) -> str:
    d = session_dir(session_id) / "recon" / f"{tool}.txt"
    d.write_text(content[:500_000], encoding="utf-8")
    return str(d.relative_to(ROOT.parent.parent.parent))


def add_evidence(session: ResearchSession, kind: str, content: str, filename: str) -> EvidenceItem:
    d = session_dir(session.id) / "evidence"
    path = d / filename
    path.write_text(content[:200_000], encoding="utf-8")
    item = EvidenceItem(
        id=f"ev_{len(session.evidence)+1:04d}",
        kind=kind,
        path=str(path.relative_to(ROOT.parent.parent.parent)),
        summary=content[:200],
    )
    session.evidence.append(item.to_dict())
    save_session(session)
    return item
