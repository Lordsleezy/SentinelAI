"""Git inspection tools."""

import subprocess
from pathlib import Path

from tools import SentinelTool, ToolResult


class GitStatusTool(SentinelTool):
    name = "git_status"
    requires_approval = False

    def run(self, root: str) -> ToolResult:
        base = Path(root).resolve()
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=str(base),
            text=True,
            capture_output=True,
            timeout=15,
        )
        return ToolResult(
            result.returncode == 0,
            result.stdout,
            {"root": str(base), "returncode": result.returncode},
            result.stderr,
        )
