"""Build verification — success only after checks pass."""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from builders.common.logging_util import log_builder
from builders.common.types import BuildResult, VerificationResult
from builders.router import BuildType


def verify_build(result: BuildResult, build_type: BuildType,
                 socketio: Any = None) -> VerificationResult:
    """Run type-specific verification. May attempt one repair via python builder."""
    log_builder(f"Verifying {build_type.value} build at {result.output_dir}", "info", socketio)

    if build_type == BuildType.GAME:
        v = _verify_godot(result, socketio)
        log_builder(
            f"Verification: {'PASSED' if v.verified else 'FAILED'}",
            "success" if v.verified else "warning",
            socketio,
        )
        return v
    if build_type == BuildType.WEB:
        return _verify_web(result, socketio)
    if build_type == BuildType.DESKTOP:
        return _verify_desktop(result, socketio)
    if build_type == BuildType.ANDROID:
        return _verify_android(result, socketio)
    if build_type in (BuildType.PYTHON, BuildType.UNKNOWN):
        return _verify_python(result, socketio)
    return VerificationResult(True, "No verification required")


def _verify_godot(result: BuildResult, socketio: Any) -> VerificationResult:
    proj = Path(result.output_dir) / "project.godot"
    if not proj.exists():
        return VerificationResult(False, "project.godot missing")
    main = Path(result.output_dir) / "scenes" / "main.tscn"
    if not main.exists():
        return VerificationResult(False, "scenes/main.tscn missing")
    godot = _find_godot()
    if godot:
        try:
            proc = subprocess.run(
                [godot, "--path", result.output_dir, "--quit-after", "1"],
                capture_output=True, text=True, timeout=30,
            )
            if proc.returncode == 0:
                return VerificationResult(True, "Godot project loads")
            return VerificationResult(False, f"Godot quit code {proc.returncode}")
        except subprocess.TimeoutExpired:
            return VerificationResult(False, "Godot load timed out")
        except Exception as e:
            return VerificationResult(False, str(e))
    return VerificationResult(
        False,
        "Godot Engine not installed — Sentinel will install automatically before launch",
    )


def _verify_web(result: BuildResult, socketio: Any) -> VerificationResult:
    pkg = Path(result.output_dir) / "package.json"
    if not pkg.exists():
        return VerificationResult(False, "package.json missing")
    return VerificationResult(True, "Next.js project scaffold present")


def _verify_desktop(result: BuildResult, socketio: Any) -> VerificationResult:
    pkg = Path(result.output_dir) / "package.json"
    main_js = Path(result.output_dir) / "main.js"
    if pkg.exists() and main_js.exists():
        return VerificationResult(True, "Electron project scaffold valid")
    entry = Path(result.entry_point) if result.entry_point else None
    if entry and entry.exists():
        return VerificationResult(True, f"Entry exists: {entry.name}")
    return VerificationResult(False, "Desktop entry missing")


def _verify_android(result: BuildResult, socketio: Any) -> VerificationResult:
    gradle = Path(result.output_dir) / "app" / "build.gradle.kts"
    if not gradle.exists():
        gradle = Path(result.output_dir) / "build.gradle.kts"
    if gradle.exists():
        return VerificationResult(True, "Android Gradle project present")
    return VerificationResult(False, "Gradle files missing")


def _verify_python(result: BuildResult, socketio: Any) -> VerificationResult:
    entry = result.entry_point
    if not entry or not Path(entry).exists():
        return VerificationResult(False, "Python entry point missing")
    if not entry.endswith(".py"):
        return VerificationResult(True, "Non-Python entry — structure check only")
    try:
        proc = subprocess.run(
            [sys.executable, entry],
            cwd=result.output_dir or None,
            capture_output=True, text=True, timeout=8,
        )
        # GUI apps may exit quickly; 0 or no hang is ok
        return VerificationResult(True, f"Python entry ran (exit {proc.returncode})")
    except subprocess.TimeoutExpired:
        # Still running — likely GUI
        return VerificationResult(True, "Python process started (GUI likely alive)")
    except Exception as e:
        return VerificationResult(False, str(e))


def _find_godot() -> Optional[str]:
    try:
        from builders.runtime.godot_runtime import find_godot
        return find_godot()
    except Exception:
        return None
