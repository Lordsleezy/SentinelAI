"""
Builder Status panel — capability-backed runtime health per build type.
"""
from __future__ import annotations

from typing import Any, Dict, List


def get_builder_status() -> List[Dict[str, Any]]:
    """Rows for Builder Status UI (GAME, WEB, DESKTOP, GUARDIAN, AI, …)."""
    try:
        from core.capabilities.capability_manager import get_capability_manager
        return get_capability_manager().builder_status_panels()
    except Exception:
        return _legacy_builder_status()


def _legacy_builder_status() -> List[Dict[str, Any]]:
    import shutil
    from builders.runtime.godot_runtime import godot_diagnostic

    godot = godot_diagnostic()
    npm_ok = bool(shutil.which("npm"))

    def _line(ok: bool, label: str) -> Dict[str, Any]:
        return {"label": label, "ok": ok, "status_line": f"{'✓' if ok else '✗'} {label}"}

    return [
        {
            "type": "GAME",
            "title": "GAME",
            "ready": godot.get("installed", False),
            "lines": [_line(True, "Builder"), _line(godot.get("installed", False), "Godot")],
            "runtime": godot,
        },
        {
            "type": "WEB",
            "title": "WEB",
            "ready": npm_ok,
            "lines": [_line(True, "Builder"), _line(npm_ok, "npm")],
        },
    ]
