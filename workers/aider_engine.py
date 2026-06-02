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
    diagnostics: dict = field(default_factory=dict)  # exit_code, kill_reason, runtime, model, …


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

        proc: Optional[subprocess.Popen] = None
        runtime_seconds = 0.0
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
                        _emit(self.socketio,
                              f"Aider killed — timeout after {int(MAX_RUNTIME)}s (no completion)",
                              "error", "aider")
                        _emit(self.socketio, "Task incomplete. Check what was built and retry if needed.", "warning", "aider")
                        try: proc.kill()
                        except Exception: pass
                        return
                    if now - last_output_time > STUCK_TIMEOUT:
                        kill_reason.append("stuck")
                        _emit(self.socketio,
                              f"Aider killed — no output for {STUCK_TIMEOUT}s (watchdog)",
                              "error", "aider")
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
            runtime_seconds = round(time.time() - start_time, 2)
            success = (proc.returncode == 0) and not kill_reason
            if kill_reason:
                kr = kill_reason[0]
                if kr == "timeout":
                    error_text = f"Timeout after {int(MAX_RUNTIME)}s"
                elif kr == "stuck":
                    error_text = f"Watchdog kill: no output for {STUCK_TIMEOUT}s"
                elif kr == "loop":
                    error_text = "Loop detected in aider output"
                else:
                    error_text = f"Process killed: {kr}"
        except Exception as e:
            error_text = f"Aider execution failed: {e}"
            _emit(self.socketio, error_text, "error", "aider")
            success = False
            try:
                runtime_seconds = round(time.time() - start_time, 2)
            except Exception:
                runtime_seconds = 0.0
        finally:
            with self._lock:
                self.running = False
                self.current_process = None

        entry_point = _detect_entry_point(files_modified)
        raw_output = "\n".join(output_lines)
        diagnostics = {
            "model": self.model,
            "prompt_size_bytes": len((message or "").encode("utf-8")),
            "exit_code": proc.returncode if proc else None,
            "kill_reason": kill_reason[0] if kill_reason else None,
            "runtime_seconds": runtime_seconds,
            "max_runtime": MAX_RUNTIME,
            "stuck_timeout": STUCK_TIMEOUT,
            "output_lines": len(output_lines),
            "ollama_response_length": len(raw_output),
            "exception_text": error_text,
        }
        return AiderResult(
            success=success,
            output=raw_output,
            files_modified=files_modified,
            entry_point=entry_point,
            output_dir=work_dir,
            error=error_text,
            diagnostics=diagnostics,
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

    def analyze_bounty(
        self,
        title: str,
        url: str,
        scope: List[str],
        program_data: Optional[dict] = None,
    ) -> AiderResult:
        """
        Program-specific bug bounty analysis (HackerOne scope parsing + structured report).

        Writes memory/vault/bounties/{title}.md and {title}_intel.json
        """
        from workers.earn.earn_diagnostics import earn_log

        earn_log(self.socketio, f"ENTER analyze_bounty: {title}")

        # ── Task Manager integration ─────────────────────────────────────────
        _task_id: str = ''
        try:
            from workers.task_manager import create_task, update_task, RUNNING, COMPLETED, FAILED
            _t = create_task(f"Earn Analysis — {title[:60]}", source="earn",
                             metadata={"url": url, "title": title})
            _task_id = _t["id"]
        except Exception:
            pass

        def _earn_progress(pct: int, summary: str = '') -> None:
            if not _task_id:
                return
            try:
                from workers.task_manager import update_task, RUNNING
                update_task(_task_id, status=RUNNING, progress=pct,
                            result_summary=summary or None,
                            current_stage=summary or None)
            except Exception:
                pass

        vault_dir = Path(self.work_dir) / "memory" / "vault" / "bounties"
        vault_dir.mkdir(parents=True, exist_ok=True)

        safe_title = "".join(c if c.isalnum() or c in "-_ " else "_" for c in title)[:50]
        findings_file = vault_dir / f"{safe_title}.md"

        import json as _json
        from workers.earn.hackerone_intel import fetch_program_page_notes, resolve_program_intel
        from workers.earn.program_report import build_program_report
        from workers.earn.earn_diagnostics import persist_earn_log

        intel = None
        recommendations = []
        result: Optional[AiderResult] = None

        # ── Stage 1: Parse HackerOne program page / dataset ─────────────────────
        try:
            earn_log(self.socketio, "Stage 1/4: Parsing HackerOne program scope")
            _earn_progress(10, "Parsing program")
            intel = resolve_program_intel(title, url, scope, program_data)
            page_notes = fetch_program_page_notes(intel.handle)
            intel.authentication_notes.extend(page_notes)
            earn_log(
                self.socketio,
                f"Parsed {intel.name} — {len(intel.in_scope)} in-scope, "
                f"{len(intel.out_of_scope)} out-of-scope, {len(intel.mobile_targets)} mobile",
            )
            _earn_progress(25, f"{len(intel.in_scope)} assets mapped")
        except Exception as _se:
            earn_log(self.socketio, f"Stage 1 error: {_se}", "error")
            return AiderResult(success=False, output="", error=f"Program parse failed: {_se}")

        intel_path = vault_dir / f"{safe_title}_intel.json"
        try:
            intel_path.write_text(_json.dumps(intel.to_dict(), indent=2), encoding="utf-8")
        except Exception:
            pass

        # ── Stage 2: Build attack surface map ───────────────────────────────────
        try:
            earn_log(self.socketio, "Stage 2/4: Building attack surface map")
            _earn_progress(40, "Attack surface map")
            report_md, recommendations, surface_map = build_program_report(intel)
            earn_log(
                self.socketio,
                f"Attack surface: {len(surface_map)} categories, "
                f"{len(recommendations)} program-specific recommendations",
            )
        except Exception as _de:
            earn_log(self.socketio, f"Stage 2 error: {_de}", "error")
            if _task_id:
                try:
                    from workers.task_manager import update_task, FAILED
                    update_task(_task_id, status=FAILED, error=str(_de))
                except Exception:
                    pass
            return AiderResult(success=False, output="", error=f"Report build failed: {_de}")

        # ── Stage 3: Write program-specific report ──────────────────────────────
        try:
            earn_log(self.socketio, "Stage 3/4: Writing program-specific report")
            _earn_progress(65, "Writing report")
            findings_file.write_text(report_md, encoding="utf-8")
            earn_log(self.socketio, f"Report written: {findings_file.name} ({len(report_md)} chars)")
            eligible = sum(1 for a in intel.in_scope if a.eligible_for_bounty)
            min_recs = min(3, max(1, eligible))
            ok = len(recommendations) >= min_recs
            result = AiderResult(
                success=ok,
                output=report_md[:4000],
                files_modified=[str(findings_file)],
                entry_point=str(findings_file),
                output_dir=str(vault_dir),
                error=None if ok else "Insufficient asset-specific recommendations",
                diagnostics={
                    "recommendation_count": len(recommendations),
                    "in_scope_count": len(intel.in_scope),
                    "program_handle": intel.handle,
                },
            )
        except Exception as _we:
            earn_log(self.socketio, f"Stage 3 error: {_we}", "error")
            return AiderResult(success=False, output="", error=f"Write failed: {_we}")

        # Optional LLM polish (must not replace asset-specific content)
        if os.getenv("EARN_LLM_POLISH", "").lower() in ("1", "true", "yes"):
            earn_log(self.socketio, "Optional LLM polish enabled (EARN_LLM_POLISH)")
            _earn_progress(75, "LLM polish")
            polish_prompt = (
                "Review the markdown bug bounty report. Add at most 2 sentences of context "
                "under 'Researcher Notes' only. Do NOT remove or replace asset names. "
                "Do NOT add generic SQLi/XSS/buffer overflow checklist items."
            )
            try:
                polish = self._run_aider(polish_prompt, [str(findings_file)], str(vault_dir), ["--no-git"])
                if not polish.success:
                    earn_log(self.socketio, f"LLM polish skipped: {polish.error}", "warning")
            except Exception as _pe:
                earn_log(self.socketio, f"LLM polish error: {_pe}", "warning")

        persist_earn_log(self.work_dir, title, {
            "title": title,
            "url": url,
            "intel": intel.to_dict(),
            "recommendations": [r.to_dict() for r in recommendations[:25]],
            "raw_output": report_md,
            "success": result.success,
        })

        # ── Stage 4: Compile summary ────────────────────────────────────────────
        try:
            earn_log(self.socketio, "Stage 4/4: Compiling recommendations")
            _earn_progress(90, "Summary")
            if result and result.success:
                preview_lines = [
                    f"- {r.title} (confidence {r.confidence:.0%}, target `{r.target}`)"
                    for r in recommendations[:6]
                ]
                earn_log(
                    self.socketio,
                    f"SUCCESS Program-specific analysis for {intel.name}:\n" + "\n".join(preview_lines),
                    "success",
                )
                earn_log(self.socketio, f"Saved: {findings_file} + {intel_path.name}", "success")
                if _task_id:
                    try:
                        from workers.task_manager import update_task, COMPLETED
                        update_task(
                            _task_id, status=COMPLETED, progress=100,
                            result_summary=f"{len(recommendations)} recs | {len(intel.in_scope)} assets",
                        )
                    except Exception:
                        pass
            else:
                earn_log(self.socketio, f"FAIL: {result.error or 'Report incomplete'}", "error")
                if _task_id:
                    try:
                        from workers.task_manager import update_task, FAILED
                        update_task(_task_id, status=FAILED, error=result.error or "incomplete")
                    except Exception:
                        pass
        except Exception as _re:
            earn_log(self.socketio, f"Stage 4 error: {_re}", "error")

        earn_log(self.socketio, f"EXIT analyze_bounty: {'SUCCESS' if (result and result.success) else 'FAIL'}")
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
