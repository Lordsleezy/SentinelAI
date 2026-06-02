"""
Launch Verifier — build success requires launch attempt + outcome.
"""
from __future__ import annotations

import subprocess
import time
from typing import Any, Dict, Optional, Tuple

from builders.common.types import BuildResult
from builders.router import BuildType


def verify_launch(
    result: BuildResult,
    build_type: BuildType,
    artifact: Optional[Dict] = None,
    socketio: Any = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Attempt launch after build. Returns (launch_verified, message, details).
    """
    try:
        from workers.artifacts.artifact_registry import launch_artifact
    except Exception as e:
        return False, f"Launch module unavailable: {e}", {}

    art = artifact or {
        "task": result.output_dir,
        "entry_point": result.entry_point,
        "output_dir": result.output_dir,
        "launch_command": result.launch_command,
        "builder_used": result.builder,
        "project_type": result.project_type,
        "artifact_type": result.artifact_type,
    }

    launch_result = launch_artifact(art)

    if launch_result.get("ok"):
        return True, launch_result.get("message", "Launch successful"), launch_result

    if launch_result.get("needs_install"):
        dep = launch_result.get("dependency", "unknown")
        return False, f"Launch blocked: {dep} required — install in progress or user prompt", launch_result

    if build_type == BuildType.WEB:
        return _verify_web_dev_server(result)

    err = launch_result.get("error", "Launch failed")
    return False, err, launch_result


def _verify_web_dev_server(result: BuildResult) -> Tuple[bool, str, Dict[str, Any]]:
    """Run npm install + npm run dev briefly for WEB projects."""
    import os
    from pathlib import Path

    out = Path(result.output_dir)
    pkg = out / "package.json"
    if not pkg.is_file():
        return False, "package.json missing", {}

    npm = "npm"
    try:
        subprocess.run(
            [npm, "install"],
            cwd=str(out),
            capture_output=True,
            text=True,
            timeout=180,
            shell=os.name == "nt",
        )
        proc = subprocess.Popen(
            [npm, "run", "dev"],
            cwd=str(out),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=os.name == "nt",
        )
        time.sleep(4)
        if proc.poll() is None:
            proc.terminate()
            return True, "Dev server started (npm run dev)", {"command": "npm run dev"}
        return False, f"Dev server exited early (code {proc.returncode})", {}
    except subprocess.TimeoutExpired:
        return False, "npm install timed out", {}
    except Exception as e:
        return False, str(e), {}
