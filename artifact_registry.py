"""
artifact_registry.py — Persistent build artifact registry for SentinelAI.

Stores metadata about completed builds so Sentinel can remember what was
built and launch it when the user says "launch it", "run it", etc.

Storage: JSON file at memory/vault/artifacts/registry.json
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_REGISTRY_PATH = Path(__file__).parent / "memory" / "vault" / "artifacts" / "registry.json"
_MAX_ENTRIES = 50


def _load() -> List[Dict]:
    """Load artifact registry from disk. Returns empty list on any error."""
    try:
        _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        if _REGISTRY_PATH.exists():
            with open(_REGISTRY_PATH, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except Exception as e:
        logger.debug("[ARTIFACT] Load error: %s", e)
    return []


def _save(entries: List[Dict]) -> None:
    """Persist artifact registry to disk."""
    try:
        _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(entries[-_MAX_ENTRIES:], f, indent=2)
    except Exception as e:
        logger.error("[ARTIFACT] Save error: %s", e)


def register_artifact(
    task: str,
    entry_point: Optional[str],
    output_dir: Optional[str],
    files: List[str],
    launch_command: Optional[str] = None,
) -> Dict:
    """
    Register a completed build artifact.

    Args:
        task:           Human-readable task description ("calculator", "todo app", ...)
        entry_point:    Absolute path to the main file to run
        output_dir:     Directory where files were created
        files:          All files created/modified
        launch_command: Override launch command (optional — auto-derived from entry_point)

    Returns:
        The registered artifact dict.
    """
    # Auto-derive launch command from entry point
    if not launch_command and entry_point:
        ext = Path(entry_point).suffix.lower()
        if ext == ".py":
            python = _find_python()
            launch_command = f"{python} {entry_point}"
        elif ext in (".exe", ".bat", ".cmd"):
            launch_command = entry_point
        elif ext == ".html":
            launch_command = f"open:{entry_point}"
        else:
            launch_command = entry_point

    artifact = {
        "task": task,
        "entry_point": entry_point,
        "output_dir": output_dir,
        "files": files[:20],
        "launch_command": launch_command,
        "timestamp": datetime.now().isoformat(),
    }

    entries = _load()
    entries.append(artifact)
    _save(entries)
    logger.info("[ARTIFACT] Registered: %s → %s", task, entry_point)
    return artifact


def get_latest_artifact() -> Optional[Dict]:
    """Return the most recently registered artifact, or None."""
    entries = _load()
    return entries[-1] if entries else None


def get_artifact_by_task(task_fragment: str) -> Optional[Dict]:
    """Return the most recent artifact whose task name contains task_fragment (case-insensitive)."""
    entries = _load()
    frag = task_fragment.lower()
    for entry in reversed(entries):
        if frag in (entry.get("task") or "").lower():
            return entry
    return None


def list_artifacts(limit: int = 10) -> List[Dict]:
    """Return the most recent N artifacts."""
    return _load()[-limit:]


def launch_artifact(artifact: Dict) -> Dict:
    """
    Launch the artifact. Returns {"status": "launched"|"error", "message": "..."}.
    """
    entry_point = artifact.get("entry_point") or ""
    launch_cmd = artifact.get("launch_command") or ""
    task = artifact.get("task", "unknown")

    logger.info("[ARTIFACT] Launching: %s — entry_point=%s", task, entry_point)

    if not entry_point and not launch_cmd:
        msg = f"No entry point for artifact '{task}'."
        logger.warning("[ARTIFACT] %s", msg)
        return {"status": "error", "message": msg}

    try:
        if launch_cmd.startswith("open:"):
            url_or_path = launch_cmd[5:]
            webbrowser.open(url_or_path)
            return {"status": "launched", "message": f"✓ Launching {task} in browser."}

        target = entry_point or ""
        if not os.path.exists(target):
            return {"status": "error", "message": f"File not found: {target}"}

        ext = Path(target).suffix.lower()
        if ext == ".py":
            python = _find_python()
            if os.name == "nt":
                subprocess.Popen(
                    [python, target],
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
            else:
                subprocess.Popen([python, target])
        elif ext in (".exe", ".bat", ".cmd"):
            subprocess.Popen([target], shell=True)
        elif ext == ".html":
            webbrowser.open(target)
        else:
            if os.name == "nt":
                os.startfile(target)
            else:
                subprocess.Popen(["xdg-open", target])

        logger.info("[ARTIFACT] Launched: %s", task)
        return {"status": "launched", "message": f"✓ Launching {task} ({Path(target).name})"}

    except Exception as e:
        msg = f"Launch failed: {e}"
        logger.error("[ARTIFACT] %s", msg)
        return {"status": "error", "message": msg}


def launch_latest() -> Dict:
    """Launch the most recently built artifact."""
    artifact = get_latest_artifact()
    if not artifact:
        return {"status": "error", "message": "No builds registered. Build something first."}
    return launch_artifact(artifact)


def _find_python() -> str:
    """Return the best Python executable path."""
    venv_py = Path(__file__).parent / "venv" / "Scripts" / "python.exe"
    if venv_py.exists():
        return str(venv_py)
    venv_py_unix = Path(__file__).parent / "venv" / "bin" / "python"
    if venv_py_unix.exists():
        return str(venv_py_unix)
    return sys.executable or "python"
