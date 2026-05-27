"""Terminal tool wrappers."""

import os
import subprocess
from pathlib import Path

from tools import SentinelTool, ToolResult


class DryRunTerminalTool(SentinelTool):
    """Allowlisted terminal command runner honoring DRY_RUN by default."""

    name = "terminal_dry_run"
    requires_approval = True
    allowed = {"python", "py", "git", "pytest"}

    def run(self, command: list, cwd: str = ".") -> ToolResult:
        if not command or command[0] not in self.allowed:
            return ToolResult(False, "", {"command": command}, "command not allowlisted")
        if os.getenv("DRY_RUN", "false").lower() == "true":
            return ToolResult(True, f"DRY_RUN: would run {command}", {"command": command, "cwd": cwd})
        result = subprocess.run(
            command,
            cwd=str(Path(cwd).resolve()),
            text=True,
            capture_output=True,
            timeout=120,
        )
        return ToolResult(
            result.returncode == 0,
            result.stdout,
            {"command": command, "cwd": cwd, "returncode": result.returncode},
            result.stderr,
        )
