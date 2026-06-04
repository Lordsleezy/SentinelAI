"""Workflow recorder — persist successful playbooks for reuse."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[3]
_PLAYBOOK_DIR = _ROOT / "data" / "sentinelvision" / "workflows"
_LEGACY_PLAYBOOK_DIR = _ROOT / "data" / "sentinelvision" / "playbooks"


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return s[:48] or "goal"


def save_playbook(
    provider_id: str,
    objective: str,
    plan: Dict[str, Any],
    research: Dict[str, Any],
    *,
    verification: Optional[Dict[str, Any]] = None,
) -> str:
    _PLAYBOOK_DIR.mkdir(parents=True, exist_ok=True)
    name = f"playbook_{provider_id}_{_slug(objective)}.json"
    path = _PLAYBOOK_DIR / name
    payload = {
        "provider_id": provider_id,
        "objective": objective,
        "plan": plan,
        "research_summary": research.get("summary", research),
        "verification": verification or {},
        "version": 1,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(path)


def load_playbook(provider_id: str, objective: str) -> Optional[Dict[str, Any]]:
    fname = f"playbook_{provider_id}_{_slug(objective)}.json"
    path = _PLAYBOOK_DIR / fname
    if not path.is_file():
        for d in _playbook_dirs():
            for p in d.glob(f"playbook_{provider_id}_*.json"):
                path = p
                break
            if path.is_file():
                break
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _playbook_dirs() -> List[Path]:
    dirs = []
    if _PLAYBOOK_DIR.is_dir():
        dirs.append(_PLAYBOOK_DIR)
    if _LEGACY_PLAYBOOK_DIR.is_dir() and _LEGACY_PLAYBOOK_DIR != _PLAYBOOK_DIR:
        dirs.append(_LEGACY_PLAYBOOK_DIR)
    legacy_scrub = _ROOT / "data" / "sentinelscrub" / "playbooks"
    if legacy_scrub.is_dir():
        dirs.append(legacy_scrub)
    return dirs or [_PLAYBOOK_DIR]


def list_playbooks() -> List[Dict[str, Any]]:
    out = []
    seen = set()
    for d in _playbook_dirs():
        if not d.is_dir():
            continue
        for p in sorted(d.glob("playbook_*.json")):
            if p.name in seen:
                continue
            seen.add(p.name)
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                data["path"] = str(p)
                out.append(data)
            except Exception:
                continue
    return out
