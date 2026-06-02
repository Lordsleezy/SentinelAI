"""
Forge Build Engine — orchestrates builder routing, OpenHands, verification, artifacts.

Foundation for Sentinel Forge (device testing, vision, autonomous debug — future).
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from builders.common.logging_util import log_builder
from builders.common.openhands_worker import run_openhands_session
from builders.common.types import BuildResult, VerificationResult
from builders.common.verify import verify_build
from builders.router import BuildType, route_build
from builders.android_builder import AndroidBuilder
from builders.desktop_builder import DesktopBuilder
from builders.game_builder import GameBuilder
from builders.python_builder import PythonBuilder
from builders.web_builder import WebBuilder


ProgressFn = Callable[[int, str], None]


class ForgeBuildEngine:
    """Sentinel build orchestrator — specialized builders with Aider fallback."""

    def __init__(self, socketio: Any = None):
        self.socketio = socketio
        self._builders = {
            BuildType.GAME: GameBuilder(socketio),
            BuildType.ANDROID: AndroidBuilder(socketio),
            BuildType.WEB: WebBuilder(socketio),
            BuildType.DESKTOP: DesktopBuilder(socketio),
            BuildType.PYTHON: PythonBuilder(socketio),
            BuildType.UNKNOWN: PythonBuilder(socketio),
        }

    def build(
        self,
        description: str,
        output_dir: Optional[str] = None,
        on_progress: Optional[ProgressFn] = None,
    ) -> BuildResult:
        def _prog(pct: int, msg: str) -> None:
            if on_progress:
                on_progress(pct, msg)
            log_builder(f"{msg} ({pct}%)", "info", self.socketio)

        _prog(5, "Planning")
        build_type = route_build(description, self.socketio)

        _prog(15, "Generating")
        oh = run_openhands_session(description, output_dir or "", self.socketio)
        if oh and oh.success:
            result = oh
        else:
            builder = self._builders.get(build_type, self._builders[BuildType.UNKNOWN])
            result = builder.build(description, output_dir)

        if not result.success:
            log_builder(f"Primary builder failed — Aider fallback", "warning", self.socketio)
            _prog(25, "Fallback (Python/Aider)")
            result = self._builders[BuildType.PYTHON].build(description, output_dir)

        _prog(60, "Testing")
        _prog(70, "Verifying")
        verification = verify_build(result, build_type, self.socketio)
        result.verification = verification

        if not verification.verified and build_type != BuildType.PYTHON:
            log_builder("Verification failed — attempting repair via Python/Aider", "warning", self.socketio)
            _prog(75, "Debugging")
            repair = self._builders[BuildType.PYTHON].build(
                f"Fix and complete this project: {description}. Output dir: {result.output_dir}",
                result.output_dir,
            )
            if repair.success:
                verification2 = verify_build(repair, BuildType.PYTHON, self.socketio)
                if verification2.verified:
                    repair.verification = VerificationResult(True, verification2.message, attempted_repair=True)
                    result = repair
                    build_type = BuildType.PYTHON
                else:
                    result.verification = VerificationResult(
                        False,
                        f"{verification.message}; repair did not verify",
                        attempted_repair=True,
                    )
            else:
                result.verification = VerificationResult(
                    False, verification.message, attempted_repair=True,
                )

        _prog(90, "Launching")
        if result.verification and result.verification.verified:
            _prog(100, "Completed")
            result.success = True
        else:
            _prog(100, "Completed (unverified)")
            msg = result.verification.message if result.verification else "verification skipped"
            log_builder(f"Build finished unverified: {msg}", "warning", self.socketio)

        return result
