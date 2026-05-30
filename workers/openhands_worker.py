"""workers/openhands_worker.py — capable repair option backed by OpenHands.

Used for COMPLEX issues (complexity score > 0.6). OpenHands autonomously
repairs a GitHub issue, ideally inside a Docker sandbox; falls back to a
subprocess headless run when the Python package is present without Docker.

Degrades gracefully: if neither the `openhands` package nor a usable runtime
is present, is_available() returns False and run_openhands_repair() returns a
structured "unavailable" result. Never hard-fails.

NOTE (this machine): Docker is not installed, so the sandboxed runtime is
unavailable. The module still imports and reports availability correctly so the
router can fall back to Aider / the built-in executor.
"""
from __future__ import annotations

import logging
import shutil
from typing import Dict

logger = logging.getLogger(__name__)


def _have(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:
        return False


def docker_available() -> bool:
    return shutil.which("docker") is not None


def package_available() -> bool:
    return _have("openhands")


def is_available() -> bool:
    """OpenHands is usable if the package is importable (Docker preferred but
    a subprocess fallback is attempted when Docker is absent)."""
    return package_available()


def runtime_mode() -> str:
    if not package_available():
        return "unavailable"
    return "docker" if docker_available() else "subprocess"


def run_openhands_repair(issue_url: str, repo_path: str, timeout: int = 1800) -> Dict:
    """Autonomously repair a GitHub issue with OpenHands.
       Returns {status, pr_url, files_changed, summary, worker, runtime, error}.
    """
    result = {
        "worker": "openhands",
        "runtime": runtime_mode(),
        "status": "unavailable",
        "pr_url": None,
        "files_changed": [],
        "summary": "",
        "error": None,
    }
    if not package_available():
        result["error"] = ("openhands not installed (pip install openhands-ai). "
                           "Docker also recommended for the sandboxed runtime.")
        return result

    # Package present. Prefer the headless resolver entrypoint via subprocess so
    # we never block the event loop and tolerate version drift.
    import subprocess
    cmd = ["python", "-m", "openhands.resolver.resolve_issue",
           "--repo", repo_path, "--issue", issue_url]
    try:
        proc = subprocess.run(cmd, cwd=repo_path or None, text=True,
                              capture_output=True, timeout=timeout, check=False)
        result["status"] = "completed" if proc.returncode == 0 else "failed"
        result["summary"] = (proc.stdout or "")[-2000:]
        result["files_changed"] = _changed_files(repo_path)
        if proc.returncode != 0:
            result["error"] = (proc.stderr or "")[-1000:]
        return result
    except subprocess.TimeoutExpired:
        result["status"] = "failed"
        result["error"] = f"openhands timed out after {timeout}s"
        return result
    except Exception as exc:
        logger.exception("openhands repair failed")
        result["status"] = "error"
        result["error"] = str(exc)
        return result


def _changed_files(repo_path: str):
    if not repo_path:
        return []
    try:
        import subprocess
        out = subprocess.run(["git", "diff", "--name-only"], cwd=repo_path,
                             text=True, capture_output=True, timeout=20, check=False)
        return [line for line in out.stdout.splitlines() if line.strip()]
    except Exception:
        return []
