"""
Forge Build Engine — orchestrates builder routing, verification, artifacts.

Foundation for Sentinel Forge (device testing, vision, autonomous debug — future).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from builders.build_tracker import update_build
from builders.common.logging_util import log_builder
from builders.common.openhands_worker import run_openhands_session
from builders.common.types import BuildResult, VerificationResult
from builders.common.verify import verify_build
from builders.router import BuildType, engine_for_route, route_build
from builders.android_builder import AndroidBuilder
from builders.desktop_builder import DesktopBuilder
from builders.game_builder import GameBuilder
from builders.python_builder import PythonBuilder
from builders.web_builder import WebBuilder


ProgressFn = Callable[[int, str], None]

_TOTAL_STAGES = 9


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

    def _stage(self, n: int, name: str, pct: int, on_progress: Optional[ProgressFn]) -> None:
        label = f"Stage {n}/{_TOTAL_STAGES} {name}"
        log_builder(label, "info", self.socketio)
        update_build(current_stage=name, progress_percent=pct)
        if on_progress:
            on_progress(pct, name)

    def _log_created_files(self, files: list) -> None:
        for f in files:
            p = Path(f)
            log_builder(f"Created {p.name}", "info", self.socketio)
            update_build(file_created=str(p))

    def build(
        self,
        description: str,
        output_dir: Optional[str] = None,
        on_progress: Optional[ProgressFn] = None,
        build_type: Optional[BuildType] = None,
    ) -> BuildResult:
        if build_type is None:
            self._stage(1, "Planning", 5, on_progress)
            build_type = route_build(description, self.socketio)
        else:
            self._stage(1, "Planning", 5, on_progress)
            log_builder(f"Route: {build_type.value}", "info", self.socketio)
            log_builder(f"Engine: {engine_for_route(build_type)}", "info", self.socketio)

        update_build(engine=engine_for_route(build_type))

        # ── Stage 2–3: Capability check + install ─────────────────────────────
        self._stage(2, "Dependency Check", 12, on_progress)
        from core.capabilities.capability_manager import get_capability_manager
        cap = get_capability_manager(self.socketio)
        cap_result = cap.ensure_for_build_type(
            build_type.value,
            auto_install=True,
            on_progress=on_progress,
            log_fn=lambda m, lvl="info": log_builder(m, lvl, self.socketio),
        )
        self._stage(3, "Dependency Install", 18, on_progress)
        if not cap_result.get("ok") and cap_result.get("errors"):
            err = "; ".join(cap_result["errors"])
            log_builder(f"Capability install incomplete: {err}", "warning", self.socketio)
            if build_type == BuildType.GAME:
                return BuildResult(
                    success=False,
                    builder="Forge",
                    project_type=build_type.value,
                    error=f"Required runtime missing: {err}",
                    verification=VerificationResult(False, err),
                )

        # ── Stage 4: Generate ─────────────────────────────────────────────────
        gen_label = "Generating Scenes" if build_type == BuildType.GAME else "Generating"
        self._stage(4, gen_label, 30, on_progress)

        result: BuildResult
        # OpenHands can override specialized scaffolds — skip for GAME (Godot).
        oh = None
        if build_type != BuildType.GAME:
            oh = run_openhands_session(description, output_dir or "", self.socketio)

        if oh and oh.success:
            result = oh
            log_builder(f"Engine: {result.builder} (OpenHands)", "info", self.socketio)
        else:
            builder = self._builders.get(build_type, self._builders[BuildType.UNKNOWN])
            result = builder.build(description, output_dir)
            log_builder(f"Engine: {result.builder}", "info", self.socketio)

        if result.files:
            self._log_created_files(result.files)

        if not result.success:
            log_builder("Primary builder failed — Aider fallback", "warning", self.socketio)
            self._stage(4, "Fallback (Python/Aider)", 38, on_progress)
            result = self._builders[BuildType.PYTHON].build(description, output_dir)
            if result.files:
                self._log_created_files(result.files)

        # ── Stage 5: Build ──────────────────────────────────────────────────────
        self._stage(5, "Build", 50, on_progress)

        # ── Stage 6: Verifying ────────────────────────────────────────────────────
        self._stage(6, "Verifying", 62, on_progress)
        verification = verify_build(result, build_type, self.socketio)
        result.verification = verification
        vlabel = "PASSED" if verification.verified else "FAILED"
        log_builder(f"Verification {vlabel}", "success" if verification.verified else "warning", self.socketio)
        update_build(verification=vlabel)

        if not verification.verified and build_type != BuildType.PYTHON:
            log_builder("Verification failed — attempting repair via Python/Aider", "warning", self.socketio)
            self._stage(8, "Self Repair", 75, on_progress)
            repair = self._builders[BuildType.PYTHON].build(
                f"Fix and complete this project: {description}. Output dir: {result.output_dir}",
                result.output_dir,
            )
            if repair.success and repair.files:
                self._log_created_files(repair.files)
            if repair.success:
                verification2 = verify_build(repair, BuildType.PYTHON, self.socketio)
                v2 = "PASSED" if verification2.verified else "FAILED"
                log_builder(f"Verification {v2} (after repair)", "success" if verification2.verified else "warning", self.socketio)
                update_build(verification=v2)
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

        result.success = bool(result.verification and result.verification.verified)
        if not result.success:
            result.error = result.verification.message if result.verification else "Verification failed"
            return result

        # ── Stage 7: Launch (attempt) — final success in _run_forge_build ───────
        self._stage(7, "Launch", 82, on_progress)

        # Stage 8–9 (self-repair on launch fail, register, complete) in _run_forge_build.
        return result
