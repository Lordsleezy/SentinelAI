"""
Run ProjectDiscovery-style CLI tools with stdin wordlists and structured stage logging.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Callable, List, Optional

from workers.guardian.bundled_toolchain import resolve_tool_binary


def run_tool(
    tool_id: str,
    args: List[str],
    *,
    stdin_lines: Optional[List[str]] = None,
    timeout: int = 120,
    log_fn: Optional[Callable[[str, str], None]] = None,
) -> tuple[int, str, str]:
    resolved = resolve_tool_binary(tool_id)
    if not resolved:
        return -1, "", f"{tool_id} not installed"

    cmd = [resolved.path] + args
    stdin_data = None
    tmp: Optional[Path] = None
    if stdin_lines:
        stdin_data = "\n".join(stdin_lines) + "\n"

    if log_fn:
        log_fn(f"[GUARDIAN] Running {tool_id}: {' '.join(args[:8])}", "info")

    try:
        proc = subprocess.run(
            cmd,
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        return -2, "", f"{tool_id} timed out after {timeout}s"
    except Exception as e:
        return -3, "", str(e)
