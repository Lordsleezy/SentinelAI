"""
workers/aider_engine.py — Aider-powered build engine for SentinelAI.

Wraps the Aider CLI as a subprocess, streaming every output line to the
Socket.IO log_event channel so the Log tab shows live progress.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# Path to aider inside the project venv
_VENV_AIDER = Path(__file__).parent.parent / "venv" / "Scripts" / "aider.exe"
_VENV_AIDER_UNIX = Path(__file__).parent.parent / "venv" / "bin" / "aider"


def _find_aider() -> str:
    """Return the aider executable path or raise if not found."""
    for candidate in [str(_VENV_AIDER), str(_VENV_AIDER_UNIX), "aider"]:
        try:
            if os.path.isfile(candidate) or candidate == "aider":
                result = subprocess.run(
                    [candidate, "--version"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    return candidate
        except Exception:
            continue
    raise FileNotFoundError("aider not found. Run: pip install aider-chat")


@dataclass
class AiderResult:
    success: bool
    output: str
    files_modified: List[str] = field(default_factory=list)
    entry_point: Optional[str] = None   # main file to launch (absolute path)
    output_dir: Optional[str] = None    # directory where files were saved
    error: Optional[str] = None


def _detect_entry_point(files_modified: List[str]) -> Optional[str]:
    """Pick the most likely entry point from a list of modified files."""
    entry_names = ['main.py', 'app.py', 'run.py', 'clock.py', 'index.py', 'start.py']
    py_files = [f for f in files_modified if f.endswith('.py')]
    for name in entry_names:
        for f in py_files:
            if os.path.basename(f).lower() == name:
                return f
    return py_files[0] if py_files else (files_modified[0] if files_modified else None)


def _emit(socketio: Any, message: str, level: str = "info", source: str = "aider") -> None:
    """Emit a log_event via Socket.IO (no-op if socketio is None)."""
    if socketio is None:
        logger.info("[%s] %s", source, message)
        return
    try:
        socketio.emit("log_event", {
            "type": source,
            "level": level,
            "message": message,
            "timestamp": datetime.now().isoformat(),
        })
    except Exception as e:
        logger.debug("Socket.IO emit failed: %s", e)


COMPLEXITY_KEYWORDS = [
    'react native', 'electron', 'webpack', 'vite', 'next.js', 'nextjs',
    'docker', 'kubernetes', 'microservice', 'distributed',
    'blockchain', 'neural network', 'train a model',
    'mobile app', 'ios app', 'android app', 'cross-platform',
    'expo', 'flutter', 'react native',
]

AIDER_SYSTEM_CONTEXT = (
    "IMPORTANT CONSTRAINTS:\n"
    "- Create simple, working files only\n"
    "- Maximum 3 files per task\n"
    "- Python scripts use standard library or common packages only\n"
    "- GUI apps use tkinter (not React, not Electron, not PyQt)\n"
    "- Web apps use plain HTML + vanilla JS (no bundlers, no frameworks)\n"
    "- Save all files to the specified output directory\n"
    "- Do NOT create package.json, webpack configs, or build scripts\n"
    "- The goal is a WORKING file the user can run immediately\n"
    "\nTask: "
)


class AiderEngine:
    """
    Wraps Aider CLI as a subprocess.
    Streams output line by line via Socket.IO to the log tab.
    Uses Ollama (qwen2.5-coder:14b) as the model backend,
    or falls back to Claude API if ANTHROPIC_API_KEY is set.
    """

    def __init__(self, socketio: Any = None, work_dir: Optional[str] = None):
        self.socketio = socketio
        self.work_dir = work_dir or str(Path(__file__).parent.parent)
        # Always use Ollama as primary model (local, no API costs)
        # Set AIDER_MODEL env var to override
        self.model = os.getenv("AIDER_MODEL", "ollama/qwen2.5-coder:14b")
        self.running = False
        self.current_process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    # ── Core runner ────────────────────────────────────────────────────────────

    def _run_aider(self, message: str, files: List[str] = None,
                   cwd: Optional[str] = None, extra_flags: List[str] = None) -> AiderResult:
        """Low-level: build the aider command and stream its output."""
        try:
            aider_bin = _find_aider()
        except FileNotFoundError as e:
            _emit(self.socketio, str(e), "error", "aider")
            return AiderResult(success=False, output="", error=str(e))

        work_dir = cwd or self.work_dir
        cmd = [
            aider_bin,
            "--model", self.model,
            "--yes",                  # auto-confirm all changes
            "--no-auto-commits",      # don't auto git-commit
            "--no-show-model-warnings",  # suppress model warning prompts
            "--message", message,
        ]

        # Add --no-git if the work_dir has no git repo OR caller requested it
        extra_flags = extra_flags or []
        git_dir = Path(work_dir) / ".git"
        force_no_git = "--no-git" in extra_flags
        if not git_dir.exists() or force_no_git:
            cmd.append("--no-git")

        # Add remaining extra_flags (skip --no-git since we handled it)
        cmd.extend(f for f in extra_flags if f != "--no-git")

        if files:
            cmd.extend(files)

        _emit(self.socketio, f"Running: {' '.join(cmd[:6])} ...", "info", "aider")
        _emit(self.socketio, f"Working dir: {work_dir}", "info", "aider")

        output_lines: List[str] = []
        files_modified: List[str] = []
        error_text: Optional[str] = None

        # Loop / timeout / stuck detection constants
        LOOP_WINDOW = 10          # lines to inspect for repetition
        MAX_RUNTIME = 180         # 3-minute hard kill
        STUCK_TIMEOUT = 30        # kill if no output for 30s

        _file_patterns = [
            r'^Wrote\s+(.+?)$',
            r'Applied edit to\s+(.+?)$',
            r'^New file\s+(.+?)$',
            r'^Modified\s+(.+?)$',
            r'^Created\s+(.+?)$',
        ]

        try:
            env = {**os.environ, "AIDER_NO_PRETTY": "1", "NO_COLOR": "1"}
            with self._lock:
                self.running = True
                proc = subprocess.Popen(
                    cmd,
                    cwd=work_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                )
                self.current_process = proc

            start_time = time.time()
            last_output_time = time.time()
            kill_reason: List[str] = []  # mutable for closure

            def _watchdog():
                while proc.poll() is None:
                    time.sleep(2)
                    now = time.time()
                    if now - start_time > MAX_RUNTIME:
                        kill_reason.append("timeout")
                        _emit(self.socketio, "Aider killed — exceeded 3 minute hard timeout", "error", "aider")
                        _emit(self.socketio, "Task incomplete. Check what was built and retry if needed.", "warning", "aider")
                        try: proc.kill()
                        except Exception: pass
                        return
                    if now - last_output_time > STUCK_TIMEOUT:
                        kill_reason.append("stuck")
                        _emit(self.socketio, "Aider stuck — no output for 30 seconds, killed", "error", "aider")
                        _emit(self.socketio, "Partial work may exist — check the Log and output directory.", "warning", "aider")
                        try: proc.kill()
                        except Exception: pass
                        return

            watchdog_thread = threading.Thread(target=_watchdog, daemon=True)
            watchdog_thread.start()

            recent_lines: List[str] = []

            for raw_line in iter(proc.stdout.readline, ""):
                line = raw_line.rstrip()
                last_output_time = time.time()
                if not line:
                    continue
                output_lines.append(line)

                # File modification detection
                for pat in _file_patterns:
                    m = re.search(pat, line.strip(), re.IGNORECASE)
                    if m:
                        candidate = m.group(1).strip().strip('"').strip("'").rstrip('.')
                        if candidate and '.' in os.path.basename(candidate):
                            abs_path = os.path.join(work_dir, candidate) if not os.path.isabs(candidate) else candidate
                            abs_path = os.path.normpath(abs_path)
                            if abs_path not in files_modified:
                                files_modified.append(abs_path)
                        break

                # Level detection
                level = "info"
                if any(kw in line.lower() for kw in ("error", "traceback", "exception")):
                    level = "error"
                elif any(kw in line.lower() for kw in ("warning", "warn")):
                    level = "warning"
                elif any(kw in line.lower() for kw in ("success", "done", "complete", "wrote", "applied")):
                    level = "success"

                _emit(self.socketio, line, level, "aider")

                # Loop detection — check if last N non-empty lines are all identical
                stripped = line.strip()
                if stripped:
                    recent_lines.append(stripped)
                    if len(recent_lines) > LOOP_WINDOW:
                        recent_lines.pop(0)
                    if len(recent_lines) >= LOOP_WINDOW:
                        unique = set(recent_lines)
                        if len(unique) <= 2:
                            sample = list(unique)[0][:80]
                            _emit(self.socketio, f"Aider loop detected — repeating: '{sample}'", "error", "aider")
                            _emit(self.socketio, "Killed Aider. Partial work may exist — check modified files.", "warning", "aider")
                            _emit(self.socketio, "Tip: Try rephrasing the task or breaking it into smaller steps.", "info", "aider")
                            kill_reason.append("loop")
                            try: proc.kill()
                            except Exception: pass
                            break

            proc.stdout.close()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            success = (proc.returncode == 0) and not kill_reason
            if kill_reason:
                error_text = f"Killed: {kill_reason[0]}"
        except Exception as e:
            error_text = f"Aider execution failed: {e}"
            _emit(self.socketio, error_text, "error", "aider")
            success = False
        finally:
            with self._lock:
                self.running = False
                self.current_process = None

        entry_point = _detect_entry_point(files_modified)
        return AiderResult(
            success=success,
            output="\n".join(output_lines),
            files_modified=files_modified,
            entry_point=entry_point,
            output_dir=work_dir,
            error=error_text,
        )

    # ── Complexity management ───────────────────────────────────────────────────

    def is_too_complex(self, task: str) -> bool:
        """Return True if task mentions frameworks/platforms Aider can't handle well."""
        task_lower = task.lower()
        return any(kw in task_lower for kw in COMPLEXITY_KEYWORDS)

    def simplify_task(self, task: str) -> str:
        """Use Ollama to rewrite an overly complex task into something Aider can finish."""
        import requests as _req

        prompt = (
            "You are helping simplify a coding task for an AI.\n"
            "The AI works best with simple, single-file Python or HTML tasks.\n\n"
            f"Original task: {task}\n\n"
            "Rewrite this as a simple task that:\n"
            "1. Creates 1-3 files maximum\n"
            "2. Uses Python (tkinter for GUIs) or plain HTML/JS\n"
            "3. Does NOT use React Native, Electron packaging, or complex build systems\n"
            "4. Is achievable in under 2 minutes\n"
            "5. Saves output to C:\\Users\\pgg12\\Desktop\\\n\n"
            "Return ONLY the simplified task description, nothing else.\n"
            "If the task is already simple, return it unchanged."
        )
        try:
            resp = _req.post(
                'http://localhost:11434/api/generate',
                json={"model": "qwen2.5-coder:7b", "prompt": prompt, "stream": False},
                timeout=30,
            )
            if resp.status_code == 200:
                simplified = resp.json().get('response', task).strip()
                if simplified and len(simplified) > 10:
                    if simplified != task:
                        self._log(f"Task simplified: {simplified[:100]}", 'info')
                    return simplified
        except Exception:
            pass
        return task

    def _log(self, msg: str, level: str = 'info') -> None:
        _emit(self.socketio, msg, level, 'aider')

    # ── Public API ─────────────────────────────────────────────────────────────

    def run_task(self, task: str, files: List[str] = None,
                 output_dir: Optional[str] = None) -> AiderResult:
        """
        Runs Aider with the given task.
        Streams every line of output via socketio.emit('log_event', {...}).
        """
        _emit(self.socketio, f"Task: {task}", "info", "forge")
        cwd = output_dir or self.work_dir
        return self._run_aider(task, files=files or [], cwd=cwd)

    def build_app(self, description: str, output_path: Optional[str] = None) -> AiderResult:
        """
        Builds a complete application from a description.
        Creates output_path directory if needed.
        """
        # Simplify overly complex tasks before passing to Aider
        if self.is_too_complex(description):
            _emit(self.socketio, "Task complexity detected — simplifying...", "info", "aider")
            description = self.simplify_task(description)
            _emit(self.socketio, f"Simplified to: {description}", "info", "aider")

        # Auto-derive output dir from task description if not provided
        if not output_path:
            name_match = re.search(
                r'(?:build|create|make)\s+(?:a\s+)?(.+?)(?:\s+app|\s+program|\s+script|$)',
                description.lower()
            )
            app_name = name_match.group(1).replace(' ', '_') if name_match else 'sentinel_build'
            app_name = re.sub(r'[^a-z0-9_]', '', app_name)[:20]
            output_path = fr'C:\Users\pgg12\Desktop\{app_name}'

        if output_path:
            out = Path(output_path).expanduser().resolve()
            out.mkdir(parents=True, exist_ok=True)
            cwd = str(out)
            # Write a stub file to give aider something to work with
            stub = out / "main.py"
            if not stub.exists():
                stub.write_text("# Generated by SentinelAI Aider Engine\n")
            files = [str(stub)]
        else:
            cwd = self.work_dir
            files = []

        prompt = AIDER_SYSTEM_CONTEXT + description
        _emit(self.socketio, f"Building: {description[:100]}", "info", "forge")
        result = self._run_aider(prompt, files=files, cwd=cwd)

        # Fallback: scan the output directory for all files if pattern detection missed them.
        # Aider's output format varies by version — scanning the dir is the reliable fallback.
        if output_path:
            out_path = Path(output_path)
            all_found: list[str] = []
            for ext in ("*.py", "*.html", "*.js", "*.ts", "*.sh", "*.txt"):
                for f in out_path.rglob(ext):
                    fs = str(f)
                    if fs not in all_found:
                        all_found.append(fs)
            for fs in all_found:
                if fs not in result.files_modified:
                    result.files_modified.append(fs)

        # If stub was the only thing detected and the dir has more files, prefer the full set
        if result.success and not result.files_modified and files:
            for f in files:
                if os.path.exists(f) and f not in result.files_modified:
                    result.files_modified.append(f)

        if result.files_modified and not result.entry_point:
            result.entry_point = _detect_entry_point(result.files_modified)
        return result

    def fix_error(self, file_path: str, error: str) -> AiderResult:
        """Fixes a specific error in a file."""
        prompt = (
            f"Fix this error in the file:\n\nError:\n{error}\n\n"
            f"Make minimal changes to fix the issue."
        )
        _emit(self.socketio, f"Fixing error in {file_path}", "info", "aider")
        return self._run_aider(prompt, files=[file_path], cwd=str(Path(file_path).parent))

    def analyze_bounty(self, title: str, url: str, scope: List[str]) -> AiderResult:
        """
        Analyzes a bug bounty target.
        Writes findings to memory/vault/bounties/{title}.md
        Emits explicit stage progress events with [EARN] prefix — NO SILENT FAILURES.
        Hard timeout: 120 seconds total.
        """
        import concurrent.futures

        _emit(self.socketio, f"[EARN] ENTER analyze_bounty: {title}", "info", "earn")

        vault_dir = Path(self.work_dir) / "memory" / "vault" / "bounties"
        vault_dir.mkdir(parents=True, exist_ok=True)

        safe_title = "".join(c if c.isalnum() or c in "-_ " else "_" for c in title)[:50]
        findings_file = vault_dir / f"{safe_title}.md"

        # ── Stage 1: Scope extraction ────────────────────────────────────────────
        try:
            _emit(self.socketio, f"[EARN] Stage 1/4: Extracting scope for {title}...", "info", "earn")
            scope_str = ", ".join(scope[:5]) if scope else "Not specified"
            _emit(self.socketio, f"[EARN] Scope extracted: {scope_str[:120]}", "info", "earn")
        except Exception as _se:
            scope_str = "Not specified"
            _emit(self.socketio, f"[EARN] Stage 1 error (scope extraction): {_se}", "error", "earn")

        # ── Stage 2: Create analysis document stub ───────────────────────────────
        try:
            _emit(self.socketio, f"[EARN] Stage 2/4: Creating analysis document...", "info", "earn")
            findings_file.write_text(
                f"# Bug Bounty Analysis: {title}\n\n"
                f"URL: {url}\n\n"
                f"## In-Scope Targets\n\n"
                + "\n".join(f"- {s}" for s in scope[:10])
                + "\n\n## Attack Surface Analysis\n\n## Recommended Attack Vectors\n\n## Recon Plan\n"
            )
            _emit(self.socketio, f"[EARN] Stage 2/4: Document stub created at {findings_file.name}", "info", "earn")
        except Exception as _de:
            _emit(self.socketio, f"[EARN] Stage 2 error (document creation): {_de}", "error", "earn")
            result = AiderResult(success=False, output="", error=f"Analysis failed: {_de}")
            return result

        # ── Stage 3: AI analysis via Aider (120s timeout) ───────────────────────
        _emit(self.socketio, f"[EARN] Stage 3/4: Running AI analysis (max 120s)...", "info", "earn")
        prompt = (
            f"You are a professional bug bounty hunter. Analyze this program and complete "
            f"the security analysis document.\n\n"
            f"Program: {title}\nURL: {url}\nScope: {scope_str}\n\n"
            f"Fill in the Attack Surface Analysis, Recommended Attack Vectors, and Recon Plan "
            f"sections with specific, actionable security research steps. Be technical and thorough."
        )

        result: Optional[AiderResult] = None
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    self._run_aider,
                    prompt,
                    [str(findings_file)],
                    str(vault_dir),
                    ["--no-git"],
                )
                try:
                    result = future.result(timeout=120)
                except concurrent.futures.TimeoutError:
                    _emit(self.socketio, "[EARN] Analysis timed out after 120 seconds. Aborting.", "error", "earn")
                    self.stop()
                    result = AiderResult(success=False, output="", error="Analysis timed out after 120 seconds.")
        except Exception as _ae:
            _emit(self.socketio, f"[EARN] Stage 3 error (AI analysis): {_ae}", "error", "earn")
            result = AiderResult(success=False, output="", error=f"Analysis failed: {_ae}")

        # ── Stage 4: Recommendations and result ─────────────────────────────────
        try:
            _emit(self.socketio, f"[EARN] Stage 4/4: Compiling recommendations...", "info", "earn")
            if result and result.success:
                doc_text = findings_file.read_text(encoding="utf-8", errors="replace") if findings_file.exists() else ""
                rec_lines = [ln.strip() for ln in doc_text.splitlines() if ln.strip() and not ln.startswith('#')][:10]
                rec_preview = "\n".join(rec_lines) if rec_lines else "(see full document)"
                _emit(self.socketio, f"[EARN] SUCCESS Analysis complete for {title}. Recommendations:\n{rec_preview}", "success", "earn")
                _emit(self.socketio, f"[EARN] Analysis saved to {findings_file}", "success", "earn")
            else:
                err_msg = (result.error if result else "Unknown error")
                _emit(self.socketio, f"[EARN] FAIL Analysis failed: {err_msg}", "error", "earn")
        except Exception as _re:
            _emit(self.socketio, f"[EARN] Stage 4 error (recommendations): {_re}", "error", "earn")

        _emit(self.socketio, f"[EARN] EXIT analyze_bounty: {'SUCCESS' if (result and result.success) else 'FAIL'}", "info", "earn")
        return result if result else AiderResult(success=False, output="", error="Unknown analysis failure")

    def stop(self) -> None:
        """Stop any running Aider process."""
        with self._lock:
            if self.current_process:
                try:
                    self.current_process.terminate()
                except Exception:
                    pass


# Singleton for reuse across requests
_engine_instance: Optional[AiderEngine] = None
_engine_lock = threading.Lock()


def get_aider_engine(socketio: Any = None) -> AiderEngine:
    """Return a fresh AiderEngine (socketio is per-request, so always new)."""
    return AiderEngine(socketio=socketio)
