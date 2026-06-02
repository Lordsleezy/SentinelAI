"""
workers/artifacts/artifact_registry.py — Sentinel Artifact Registry

Tracks everything Sentinel creates: apps, scripts, reports, analyses, exports.

Storage: memory/vault/artifacts/registry.json  (rolling 100 entries)
Events:  artifact_created  (via existing Socket.IO)
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_REGISTRY_PATH = (
    Path(__file__).parent.parent.parent / "memory" / "vault" / "artifacts" / "registry.json"
)
_LOCK     = threading.Lock()
_registry: Dict[str, Dict] = {}
_loaded   = False
_MAX      = 100


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    with _LOCK:
        if _loaded:
            return
        try:
            _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
            if _REGISTRY_PATH.exists():
                with open(_REGISTRY_PATH, encoding="utf-8") as f:
                    data = json.load(f)
                for item in (data if isinstance(data, list) else data.values()):
                    _registry[item["id"]] = item
        except Exception as e:
            logger.debug("[ARTIFACTS] Load error: %s", e)
        _loaded = True


def _persist() -> None:
    try:
        entries = sorted(_registry.values(), key=lambda x: x.get("timestamp", ""))
        entries = entries[-_MAX:]
        _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
    except Exception as e:
        logger.error("[ARTIFACTS] Persist error: %s", e)


def _emit(event: str, payload: Dict) -> None:
    try:
        from desktop_app import socketio
        if socketio:
            socketio.emit(event, payload)
    except Exception:
        pass


def _now() -> str:
    return datetime.now().isoformat()


def _launch_log(message: str, level: str = "info") -> None:
    """Stream launch events to LOG panel (forge filter)."""
    if not message.startswith("[LAUNCH]"):
        message = f"[LAUNCH] {message}"
    logger.info(message)
    try:
        from desktop_app import socketio, log as _app_log
        _app_log(message, level, "forge")
        if socketio:
            socketio.emit("log_event", {
                "type": "forge",
                "level": level,
                "message": message,
                "timestamp": datetime.now().isoformat(),
            })
    except Exception:
        pass


def _find_godot() -> Optional[str]:
    try:
        from builders.runtime.godot_runtime import find_godot
        return find_godot()
    except Exception:
        for candidate in (
            "godot",
            "godot.exe",
            r"C:\Program Files\Godot\Godot.exe",
            r"C:\Tools\Godot.exe",
        ):
            found = shutil.which(candidate)
            if found:
                return found
            if candidate.startswith("C:") and Path(candidate).is_file():
                return candidate
        return None


def _parse_godot_launch(cmd: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (godot_executable, project_dir) from a launch command."""
    m = re.match(r'^"([^"]+)"\s+--path\s+"([^"]+)"', cmd.strip(), re.I)
    if m:
        exe, proj = m.group(1), m.group(2)
        if Path(exe).is_file():
            return exe, proj
    m = re.search(r'--path\s+"([^"]+)"', cmd, re.I) or re.search(r"--path\s+(\S+)", cmd, re.I)
    proj = m.group(1) if m else None
    exe = _find_godot()
    return exe, proj


def _artifact_path_for(entry_point: str, output_dir: str) -> str:
    """Primary project directory for launch cwd and validation."""
    if output_dir:
        return str(Path(output_dir).expanduser().resolve())
    if entry_point:
        return str(Path(entry_point).expanduser().resolve().parent)
    return ""


def _derive_launch_command(
    entry_point: str,
    output_dir: str,
    project_type: str = "",
    builder_used: str = "",
) -> str:
    """Derive launch command from project type / entry point."""
    ptype = (project_type or "").upper()
    odir = _artifact_path_for(entry_point, output_dir)

    if ptype == "GAME" or (entry_point and Path(entry_point).name == "project.godot"):
        return f'godot --path "{odir}"' if odir else ""
    if ptype == "WEB":
        return f'cd /d "{odir}" && npm install && npm run dev' if odir else ""
    if ptype == "DESKTOP":
        return f'cd /d "{odir}" && npm install && npm start' if odir else ""
    if ptype == "ANDROID":
        return f'cd /d "{odir}" && gradlew installDebug' if odir else ""
    if ptype == "PYTHON":
        if entry_point and entry_point.endswith(".py"):
            return f'python "{entry_point}"'
        return ""

    if not entry_point:
        return ""
    p = Path(entry_point)
    ext = p.suffix.lower()
    if p.name == "project.godot" or ext == ".godot":
        return f'godot --path "{odir or p.parent}"'
    if ext == ".py":
        return f'python "{entry_point}"'
    if ext in (".exe", ".bat", ".cmd"):
        return f'"{entry_point}"'
    if ext in (".html", ".htm"):
        return f'start "" "{entry_point}"'
    if ext == ".js" and p.name == "main.js" and (p.parent / "package.json").exists():
        return f'cd /d "{p.parent}" && npm start'
    if ext == ".js":
        return f'node "{entry_point}"'
    if ext == ".sh":
        return f'bash "{entry_point}"'
    return f'"{entry_point}"'


def _resolve_launch_command(artifact: Dict) -> str:
    cmd = (artifact.get("launch_command") or "").strip()
    if cmd:
        return cmd
    return _derive_launch_command(
        artifact.get("entry_point", ""),
        artifact.get("output_dir", "") or artifact.get("artifact_path", ""),
        artifact.get("project_type", ""),
        artifact.get("builder_used", ""),
    )


def _validate_launch_deps(artifact: Dict, cmd: str) -> Optional[str]:
    """Return error message if required binary is missing."""
    ptype = (artifact.get("project_type") or "").upper()
    odir = artifact.get("artifact_path") or artifact.get("output_dir") or ""

    if ptype == "GAME" or "godot" in cmd.lower():
        godot_exe, project_dir = _parse_godot_launch(cmd)
        if not godot_exe:
            return "godot_missing"
        check_dir = project_dir or odir
        if check_dir and not (Path(check_dir) / "project.godot").exists():
            return f"Godot project missing project.godot in {check_dir}"

    if ptype in ("WEB", "DESKTOP") or "npm" in cmd.lower():
        if not shutil.which("npm"):
            return "npm not found on PATH. Install Node.js from https://nodejs.org"
        if odir and not (Path(odir) / "package.json").exists():
            return f"package.json not found in {odir}"

    if ptype == "ANDROID" or "gradlew" in cmd.lower():
        if odir:
            gw = Path(odir) / "gradlew.bat"
            if not gw.exists():
                return f"gradlew.bat not found in {odir}"

    if ptype == "PYTHON" or cmd.strip().lower().startswith("python"):
        entry = artifact.get("entry_point", "")
        if entry and not Path(entry).exists():
            return f"Python entry not found: {entry}"

    return None


def _win_console_flags() -> int:
    if sys.platform == "win32":
        return subprocess.CREATE_NEW_CONSOLE
    return 0


def _execute_launch(artifact: Dict, cmd: str) -> Tuple[bool, str]:
    """
    Execute launch_command. Returns (success, user_message).
    """
    odir = artifact.get("artifact_path") or artifact.get("output_dir") or ""
    cwd = odir if odir and Path(odir).is_dir() else None
    ptype = (artifact.get("project_type") or "").upper()

    # ── Godot: explicit argv (no shell) ───────────────────────────────────────
    if ptype == "GAME" or ("godot" in cmd.lower() and "--path" in cmd.lower()):
        godot, project_dir = _parse_godot_launch(cmd)
        if not godot:
            return False, "Godot not found on PATH"
        if not project_dir:
            project_dir = odir
        if not project_dir or not Path(project_dir).exists():
            return False, f"Project directory not found: {project_dir}"
        _launch_log(f"Executing: {godot} --path {project_dir}")
        subprocess.Popen(
            [godot, "--path", project_dir],
            cwd=project_dir,
            creationflags=_win_console_flags(),
        )
        return True, f"Godot opened project at {project_dir}"

    # ── HTML: browser ─────────────────────────────────────────────────────────
    entry = artifact.get("entry_point", "")
    if entry and Path(entry).suffix.lower() in (".html", ".htm") and Path(entry).exists():
        import webbrowser
        webbrowser.open(Path(entry).as_uri())
        return True, f"Opened in browser: {entry}"

    # ── Shell workflows: npm, gradlew, cd /d ... ─────────────────────────────
    _launch_log(f"Executing shell: {cmd}")
    if sys.platform == "win32":
        subprocess.Popen(
            ["cmd.exe", "/c", cmd],
            cwd=cwd,
            creationflags=_win_console_flags(),
        )
    else:
        subprocess.Popen(
            cmd,
            shell=True,
            cwd=cwd,
            start_new_session=True,
        )
    return True, f"Launch started: {cmd}"


# ── Public API ───────────────────────────────────────────────────────────────

def register_artifact(
    task: str,
    entry_point: str = "",
    output_dir: str = "",
    files: Optional[List[str]] = None,
    launch_command: str = "",
    task_id: Optional[str] = None,
    project_id: Optional[str] = None,
    artifact_type: str = "app",
    builder_used: str = "",
    project_type: str = "",
    verification_status: str = "",
    build_logs: str = "",
) -> Dict:
    _ensure_loaded()
    artifact_path = _artifact_path_for(entry_point, output_dir)
    if not launch_command:
        launch_command = _derive_launch_command(
            entry_point, output_dir, project_type, builder_used,
        )
    artifact_id = "art_" + uuid.uuid4().hex[:10]
    artifact: Dict = {
        "id":                  artifact_id,
        "task":                task,
        "entry_point":         entry_point,
        "output_dir":          output_dir,
        "artifact_path":       artifact_path,
        "files":               files or ([entry_point] if entry_point else []),
        "launch_command":      launch_command,
        "artifact_type":       artifact_type,
        "task_id":             task_id,
        "project_id":          project_id,
        "builder_used":        builder_used,
        "project_type":        project_type,
        "verification_status": verification_status or "unknown",
        "build_logs":          (build_logs or "")[:8000],
        "timestamp":           _now(),
    }
    with _LOCK:
        _registry[artifact_id] = artifact
        _persist()
    logger.info(
        "[ARTIFACTS] Registered: %s path=%s launch=%s",
        artifact_id, artifact_path, launch_command[:80] if launch_command else "",
    )
    _emit("artifact_created", artifact)
    return dict(artifact)


def list_artifacts(
    limit: int = 20,
    project_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> List[Dict]:
    _ensure_loaded()
    items = sorted(_registry.values(), key=lambda x: x.get("timestamp", ""), reverse=True)
    if project_id:
        items = [a for a in items if a.get("project_id") == project_id]
    if task_id:
        items = [a for a in items if a.get("task_id") == task_id]
    return [dict(a) for a in items[:limit]]


def get_artifact(artifact_id: str) -> Optional[Dict]:
    _ensure_loaded()
    a = _registry.get(artifact_id)
    return dict(a) if a else None


def get_latest_artifact() -> Optional[Dict]:
    items = list_artifacts(limit=1)
    return items[0] if items else None


def get_artifact_by_task(task_hint: str) -> Optional[Dict]:
    _ensure_loaded()
    hint = task_hint.lower()
    candidates = sorted(
        [a for a in _registry.values() if hint in a.get("task", "").lower()],
        key=lambda x: x.get("timestamp", ""),
        reverse=True,
    )
    return dict(candidates[0]) if candidates else None


def launch_artifact(artifact: Dict) -> Dict:
    """
    Launch an artifact using its stored launch_command.

    Returns:
        {"ok": True, "message": ..., "command": ...} or {"ok": False, "error": ...}
    """
    artifact = dict(artifact)
    # Backfill artifact_path for older registry entries
    if not artifact.get("artifact_path"):
        artifact["artifact_path"] = _artifact_path_for(
            artifact.get("entry_point", ""),
            artifact.get("output_dir", ""),
        )

    _launch_log(f"Artifact found: {artifact.get('id', '?')} — {artifact.get('task', '')[:60]}")
    _launch_log(f"Builder: {artifact.get('builder_used') or 'unknown'}")
    _launch_log(f"Project type: {artifact.get('project_type') or 'unknown'}")
    _launch_log(f"Artifact path: {artifact.get('artifact_path') or '—'}")

    cmd = _resolve_launch_command(artifact)
    if not cmd:
        err = "No launch command stored for this artifact."
        _launch_log(err, "error")
        return {"ok": False, "error": err}

    _launch_log(f"Command: {cmd}")
    _launch_log("Checking dependencies")

    dep_err = _validate_launch_deps(artifact, cmd)
    if dep_err:
        if dep_err == "godot_missing":
            _launch_log("Godot missing", "error")
            _launch_log("Install required", "warning")
            try:
                from builders.runtime.godot_runtime import launch_dependency_error
                extra = launch_dependency_error()
            except Exception:
                extra = {
                    "needs_install": True,
                    "dependency": "godot",
                    "prompt_title": "Godot required. Install now?",
                }
            _emit("launch_dependency_prompt", {
                **extra,
                "artifact_id": artifact.get("id"),
                "project_type": artifact.get("project_type"),
            })
            return {
                "ok": False,
                "error": "Godot required. Install now?",
                "dependency": "godot",
                "needs_install": True,
                "prompt_title": extra.get("prompt_title", "Godot required. Install now?"),
                "prompt_actions": extra.get("prompt_actions", ["install", "browse", "cancel"]),
                "command": cmd,
            }
        _launch_log(dep_err, "error")
        return {"ok": False, "error": dep_err}

    try:
        ok, msg = _execute_launch(artifact, cmd)
        if ok:
            _launch_log("Launch successful", "success")
            return {"ok": True, "message": msg, "command": cmd}
        _launch_log(msg or "Launch failed", "error")
        return {"ok": False, "error": msg or "Launch failed", "command": cmd}
    except FileNotFoundError as e:
        err = f"Executable not found: {e}"
        _launch_log(err, "error")
        return {"ok": False, "error": err, "command": cmd}
    except Exception as e:
        err = str(e)
        _launch_log(f"Launch failed: {err}", "error")
        return {"ok": False, "error": err, "command": cmd}


def launch_latest() -> Dict:
    artifact = get_latest_artifact()
    if not artifact:
        return {"ok": False, "error": "No artifacts registered yet."}
    return launch_artifact(artifact)
