"""workers/aider_worker.py — fast repair option backed by Aider + local Ollama.

Used for SIMPLE issues (complexity score <= 0.6). Runs the `aider` CLI in
--yes-always mode against a local clone, pointed at a local Ollama coder model.

Degrades gracefully: if the `aider` binary is not installed, is_available()
returns False and run_aider_repair() returns a structured "unavailable" result
instead of raising. Never hard-fails.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Dict, Optional

logger = logging.getLogger(__name__)

AIDER_MODEL = "ollama/qwen2.5-coder:14b"


def is_available() -> bool:
    return shutil.which("aider") is not None


def run_aider_repair(issue_description: str, repo_path: str,
                     model: Optional[str] = None, timeout: int = 900) -> Dict:
    """Attempt an autonomous repair with Aider. Returns a standard result dict:
       {status, pr_url, files_changed, summary, worker, error}
    """
    result = {
        "worker": "aider",
        "status": "unavailable",
        "pr_url": None,
        "files_changed": [],
        "summary": "",
        "error": None,
    }
    if not is_available():
        result["error"] = "aider CLI not installed (pip install aider-chat)"
        return result
    if not repo_path or not shutil.os.path.isdir(repo_path):
        result["status"] = "error"
        result["error"] = f"repo_path not found: {repo_path}"
        return result

    cmd = [
        "aider",
        "--model", model or AIDER_MODEL,
        "--yes-always",
        "--no-auto-commits",
        "--message", issue_description,
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=repo_path, text=True, capture_output=True,
            timeout=timeout, check=False,
        )
        changed = _changed_files(repo_path)
        result["status"] = "completed" if proc.returncode == 0 else "failed"
        result["files_changed"] = changed
        result["summary"] = (proc.stdout or "")[-2000:]
        if proc.returncode != 0:
            result["error"] = (proc.stderr or "")[-1000:]
        return result
    except subprocess.TimeoutExpired:
        result["status"] = "failed"
        result["error"] = f"aider timed out after {timeout}s"
        return result
    except Exception as exc:
        logger.exception("aider repair failed")
        result["status"] = "error"
        result["error"] = str(exc)
        return result


def _changed_files(repo_path: str):
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only"], cwd=repo_path,
            text=True, capture_output=True, timeout=20, check=False,
        )
        return [line for line in out.stdout.splitlines() if line.strip()]
    except Exception:
        return []
