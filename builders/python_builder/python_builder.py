"""Python Builder — wraps existing Aider engine (scripts, utilities, fallback)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from builders.common.logging_util import log_builder
from builders.common.types import BuildResult


class PythonBuilder:
    name = "Python"
    project_type = "PYTHON"

    def __init__(self, socketio: Any = None):
        self.socketio = socketio

    def build(self, description: str, output_dir: Optional[str] = None) -> BuildResult:
        log_builder(f"Python/Aider build: {description[:80]}", "info", self.socketio)
        from workers.aider_engine import AiderEngine

        engine = AiderEngine(self.socketio)
        result = engine.build_app(description, output_dir)
        launch = ""
        if result.entry_point:
            ext = Path(result.entry_point).suffix.lower()
            if ext == ".py":
                launch = f'python "{result.entry_point}"'
            elif ext in (".html", ".htm"):
                launch = f'start "" "{result.entry_point}"'
        return BuildResult(
            success=result.success,
            builder=self.name,
            project_type=self.project_type,
            output_dir=result.output_dir or "",
            entry_point=result.entry_point or "",
            launch_command=launch,
            files=list(result.files_modified or []),
            build_logs=result.output or "",
            error=result.error,
            artifact_type="script" if "script" in description.lower() else "app",
        )
