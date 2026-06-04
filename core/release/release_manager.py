"""Release engineering — version, manifest, changelog, build verification."""
from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sentinel.release")

_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_PATH = _ROOT / "data" / "release" / "release_manifest.json"
_UPDATE_MANIFEST_PATH = _ROOT / "data" / "release" / "update_manifest.json"
_CHANGELOG_PATH = _ROOT / "CHANGELOG.md"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReleaseManager:
    def version(self) -> Dict[str, Any]:
        try:
            import build_info as bi
            return {
                "version": getattr(bi, "BUILD_VERSION", "0.0.0"),
                "build_type": getattr(bi, "BUILD_TYPE", "dev"),
                "build_date": getattr(bi, "BUILD_DATE", ""),
                "owner_mode": getattr(bi, "OWNER_MODE", False),
                "trial_days": getattr(bi, "TRIAL_DAYS", 7),
            }
        except ImportError:
            return {"version": "0.0.0", "build_type": "dev", "build_date": "", "owner_mode": False}

    def generate_update_manifest(
        self,
        *,
        channel: str = "beta",
        minimum_supported_version: str = "1.0.0",
        force_update: bool = False,
        kill_switch: bool = False,
        updates_disabled: bool = False,
    ) -> Dict[str, Any]:
        """Operator manifest for remote policy / updater (data/release/update_manifest.json)."""
        ver = self.version()
        beta_active = ver["build_type"] == "beta"
        try:
            from workers.licensing.license_manager import get_license_manager
            lm = get_license_manager()
            beta_active = ver["build_type"] == "beta" and not lm.beta_expired()
        except Exception:
            pass

        manifest = {
            "version": ver["version"],
            "channel": channel,
            "release_date": ver.get("build_date") or _utc(),
            "minimum_supported_version": minimum_supported_version,
            "force_update": force_update,
            "kill_switch": kill_switch,
            "beta_active": beta_active,
            "updates_disabled": updates_disabled,
        }
        _UPDATE_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        _UPDATE_MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

    def load_update_manifest(self) -> Optional[Dict[str, Any]]:
        if not _UPDATE_MANIFEST_PATH.is_file():
            return None
        try:
            return json.loads(_UPDATE_MANIFEST_PATH.read_text(encoding="utf-8"))
        except Exception:
            return None

    def generate_manifest(self, *, channel: str = "beta") -> Dict[str, Any]:
        ver = self.version()
        update_meta = self.generate_update_manifest(channel=channel)
        manifest = {
            "product": "SentinelAI",
            "version": ver["version"],
            "channel": channel,
            "build_type": ver["build_type"],
            "generated_at": _utc(),
            "components": self._verify_components(),
            "update_metadata": {
                "github_repo": "Lordsleezy/SentinelAI",
                "channels": ["beta", "stable"],
                "update_manifest": update_meta,
            },
        }
        _MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        _MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

    def _verify_components(self) -> List[Dict[str, Any]]:
        checks = [
            ("desktop_app.py", _ROOT / "desktop_app.py"),
            ("core/sentinelvision", _ROOT / "core" / "sentinelvision"),
            ("core/memory2", _ROOT / "core" / "memory2"),
            ("core/missions", _ROOT / "core" / "missions"),
            ("workers/guardian", _ROOT / "workers" / "guardian"),
        ]
        out = []
        for name, path in checks:
            out.append({"name": name, "exists": path.exists(), "path": str(path)})
        return out

    def verify_build(self) -> Dict[str, Any]:
        errors = []
        for c in self._verify_components():
            if not c["exists"]:
                errors.append(f"missing: {c['name']}")
        try:
            r = subprocess.run(
                ["python", "-m", "py_compile", str(_ROOT / "desktop_app.py")],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(_ROOT),
            )
            if r.returncode != 0:
                errors.append(f"py_compile: {r.stderr[:300]}")
        except Exception as e:
            errors.append(str(e))
        return {"ok": len(errors) == 0, "errors": errors, "checked_at": _utc()}

    def changelog(self, limit: int = 40) -> Dict[str, Any]:
        if _CHANGELOG_PATH.is_file():
            text = _CHANGELOG_PATH.read_text(encoding="utf-8")
            lines = text.splitlines()[:limit]
            return {"source": "CHANGELOG.md", "lines": lines}
        return self._changelog_from_git(limit)

    def _changelog_from_git(self, limit: int) -> Dict[str, Any]:
        try:
            r = subprocess.run(
                ["git", "log", f"-{limit}", "--oneline"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(_ROOT),
            )
            if r.returncode == 0:
                return {"source": "git", "lines": r.stdout.strip().splitlines()}
        except Exception as e:
            logger.debug("git changelog: %s", e)
        return {"source": "none", "lines": []}

    def load_manifest(self) -> Optional[Dict[str, Any]]:
        if not _MANIFEST_PATH.is_file():
            return None
        try:
            return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
        except Exception:
            return None


_mgr: Optional[ReleaseManager] = None


def get_release_manager() -> ReleaseManager:
    global _mgr
    if _mgr is None:
        _mgr = ReleaseManager()
    return _mgr
