#!/usr/bin/env python3
"""Smoke validation for capability runtime foundation."""
from __future__ import annotations

import sys

ROOT = __file__.replace("\\", "/").rsplit("/", 1)[0]
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

FAILURES: list[str] = []


def ok(msg: str) -> None:
    print(f"  OK  {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL {msg}")
    FAILURES.append(msg)


def main() -> int:
    print("Capability Runtime Validation\n")

    print("[1] Registry")
    try:
        from core.capabilities.capability_registry import CAPABILITIES, DOMAIN_CAPABILITIES
        if len(CAPABILITIES) < 10:
            fail(f"CAPABILITIES too small: {len(CAPABILITIES)}")
        else:
            ok(f"{len(CAPABILITIES)} capabilities registered")
        if "GAME" not in DOMAIN_CAPABILITIES:
            fail("GAME domain missing")
        else:
            ok("GAME domain defined")
    except Exception as e:
        fail(f"registry import: {e}")

    print("[2] Manager + validator")
    try:
        from core.capabilities.capability_manager import get_capability_manager
        from core.capabilities.runtime_validator import validate_capability
        mgr = get_capability_manager()
        panels = mgr.builder_status_panels()
        ok(f"{len(panels)} status panels")
        g = validate_capability("godot")
        ok(f"godot installed={g.installed} path={g.path[:40] if g.path else '-'}")
    except Exception as e:
        fail(f"manager: {e}")

    print("[3] Godot discovery (rglob)")
    try:
        from builders.runtime.godot_runtime import find_godot, godot_diagnostic
        d = godot_diagnostic()
        if d.get("installed"):
            ok(f"Godot: {d.get('path')}")
        else:
            fail("Godot not found — bundle under tools/godot/ or install")
    except Exception as e:
        fail(f"godot: {e}")

    print("[4] Verify rules (no fake pass)")
    try:
        from builders.common.verify import _verify_godot
        from builders.common.types import BuildResult
        from builders.runtime.godot_runtime import find_godot as _find_godot
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "scenes").mkdir()
            (p / "project.godot").write_text("config_version=5\n", encoding="utf-8")
            (p / "scenes" / "main.tscn").write_text("[gd_scene]", encoding="utf-8")
            br = BuildResult(True, "Godot", "GAME", output_dir=str(p))
            v = _verify_godot(br, None)
            if _find_godot():
                ok("Godot present — verify uses binary")
            elif v.verified:
                fail("Godot missing but verify passed (regression)")
            else:
                ok("Godot missing correctly fails verify")
    except Exception as e:
        fail(f"verify: {e}")

    print("[5] Forge engine stages")
    try:
        from builders.forge_engine import _TOTAL_STAGES
        if _TOTAL_STAGES != 9:
            fail(f"expected 9 stages, got {_TOTAL_STAGES}")
        else:
            ok("Forge 9-stage pipeline")
    except Exception as e:
        fail(f"forge_engine: {e}")

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}):")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
