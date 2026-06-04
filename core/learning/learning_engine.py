"""
Learning Engine — unknown task → research → capability profile → register → retry.

See LEARNING_ENGINE_ARCHITECTURE.md.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sentinel.learning")

_REGISTRY_REL = Path("memory") / "vault" / "learned_capabilities" / "registry.json"


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _registry_path() -> Path:
    p = _root() / _REGISTRY_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@dataclass
class CapabilityProfile:
    id: str
    label: str
    domain: str
    dependencies: List[str] = field(default_factory=list)
    install_steps: List[str] = field(default_factory=list)
    verify_hint: str = ""
    executor: str = ""
    notes: str = ""
    success_count: int = 0
    last_error: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "researching"  # researching | registered | verified | failed

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_engine: Optional["LearningEngine"] = None


class LearningEngine:
    """Platform learning loop — extends capability registry with discovered profiles."""

    def __init__(self) -> None:
        self._profiles: Dict[str, CapabilityProfile] = {}
        self._load()

    def _load(self) -> None:
        path = _registry_path()
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for raw in data.get("profiles", []):
                p = CapabilityProfile(**{k: v for k, v in raw.items() if k in CapabilityProfile.__dataclass_fields__})
                self._profiles[p.id] = p
        except Exception as e:
            logger.warning("Learned capability registry load failed: %s", e)

    def _save(self) -> None:
        path = _registry_path()
        path.write_text(
            json.dumps(
                {"profiles": [p.to_dict() for p in self._profiles.values()], "updated_at": datetime.now(timezone.utc).isoformat()},
                indent=2,
            ),
            encoding="utf-8",
        )

    def list_profiles(self) -> List[Dict[str, Any]]:
        return [p.to_dict() for p in self._profiles.values()]

    def register_profile(self, profile: CapabilityProfile) -> CapabilityProfile:
        profile.status = "registered"
        self._profiles[profile.id] = profile
        self._save()
        logger.info("Learned capability registered: %s", profile.id)
        return profile

    def handle_unknown(self, task_description: str, suggested_domain: str = "GENERAL") -> Dict[str, Any]:
        """
        Start learning workflow for an unknown task.
        Returns user-facing Sentinel message + optional task metadata.
        """
        profile_id = f"learned_{uuid.uuid4().hex[:8]}"
        profile = CapabilityProfile(
            id=profile_id,
            label=task_description[:80],
            domain=suggested_domain.upper(),
            notes="Auto-created from unknown task — research phase pending full automation.",
            status="researching",
        )
        self._profiles[profile_id] = profile
        self._save()

        # Inventory existing Sentinel modules that might already help
        hints: List[str] = []
        lower = task_description.lower()
        if any(k in lower for k in ("scan", "pentest", "cve", "vuln")):
            hints.append("Try Guardian engine (security tools already bundled).")
        if any(k in lower for k in ("build", "app", "game", "website")):
            hints.append("Try Builder/Forge engine with capability install.")
        if any(k in lower for k in ("bounty", "hackerone", "research")):
            hints.append("Try Earn research pipeline.")

        return {
            "ok": True,
            "profile_id": profile_id,
            "status": "researching",
            "response": (
                f"I don't have a verified workflow for that yet. I'm registering capability "
                f"**{profile_id}** and researching tooling.\n\n"
                + ("\n".join(f"- {h}" for h in hints) if hints else "- Checking installed capabilities and docs.")
            ),
            "hints": hints,
        }

    def promote_dependencies(self, profile_id: str, dependency_ids: List[str]) -> Dict[str, Any]:
        """After research, attach dependencies and attempt install via CapabilityManager."""
        profile = self._profiles.get(profile_id)
        if not profile:
            return {"ok": False, "error": "profile not found"}
        profile.dependencies = list(dependency_ids)
        profile.status = "registered"
        self._save()

        try:
            from core.capabilities.capability_manager import get_capability_manager
            result = get_capability_manager().ensure_capabilities(dependency_ids, auto_install=True)
            if result.get("ok"):
                profile.status = "verified"
                profile.success_count += 1
            else:
                profile.last_error = "; ".join(result.get("errors", []))
                profile.status = "failed"
            self._save()
            return {"ok": result.get("ok"), "profile": profile.to_dict(), "install": result}
        except Exception as e:
            profile.last_error = str(e)
            profile.status = "failed"
            self._save()
            return {"ok": False, "error": str(e)}


def get_learning_engine() -> LearningEngine:
    global _engine
    if _engine is None:
        _engine = LearningEngine()
    return _engine
