"""orchestrator.py — central brain for SentinelAI.

Wires the user-facing OpenClaw layer to the worker pool. Owns intent
parsing, the persistent top-level task queue, and the Forge approval gate.

This is the *outer* orchestrator (separate from the ``orchestration/``
package, which handles LangGraph-style internal workflows). The outer
orchestrator answers a single question: "given a user message, what
should SentinelAI do next?"

Flow for ``process_task``:

  1. Persist the task to ``orchestrator_tasks`` (status=running).
  2. ``parse_intent`` via Ollama (qwen3:14b, temperature=0).
  3. Try to dispatch via worker manager (find a registered tool).
  4. If no worker can handle it → ``needs_forge``:
        - Request approval via OpenClaw with action_type='forge_start'.
        - WAIT until the human resolves it. No timeout, ever.
        - If approved, run forge_worker.run_forge_task() and register
          the newly-built tool in the capability registry.
  5. Mark the task completed/failed and return a structured response.
"""
from __future__ import annotations

import importlib
import json
import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import db
import queue_manager as qm
from openclaw import openclaw as openclaw_module
from openclaw.openclaw import get_openclaw
from tools import registry as tool_registry
from models import model_manager

logger = logging.getLogger(__name__)


# ─── Schema for the orchestrator-level task queue ─────────────────────────────

ORCHESTRATOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS orchestrator_tasks (
    task_id          TEXT PRIMARY KEY,
    description      TEXT NOT NULL,
    source           TEXT DEFAULT 'desktop',
    context_json     TEXT DEFAULT '{}',
    intent_json      TEXT DEFAULT '{}',
    status           TEXT NOT NULL DEFAULT 'pending',
    worker           TEXT,
    approval_id      TEXT,
    result_json      TEXT,
    error            TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orchtasks_status ON orchestrator_tasks(status);
"""


_schema_lock = threading.Lock()
_schema_initialized = False


def ensure_orchestrator_table() -> None:
    global _schema_initialized
    if _schema_initialized:
        return
    with _schema_lock:
        if _schema_initialized:
            return
        with db.get_conn() as conn:
            conn.executescript(ORCHESTRATOR_SCHEMA)
        _schema_initialized = True


# ─── Intent shape ─────────────────────────────────────────────────────────────

VALID_INTENTS = {"repair", "build", "search", "monitor", "unknown"}


def _now() -> str:
    return datetime.utcnow().isoformat()


def _serialize(obj: Any) -> str:
    try:
        return json.dumps(obj, default=str)
    except Exception:
        return json.dumps({"_raw": str(obj)})


# ─── Intent parsing ───────────────────────────────────────────────────────────


def _parse_intent_keywords(text: str) -> Dict[str, Any]:
    """Cheap keyword-based intent fallback when Ollama is unavailable."""
    lowered = text.lower()
    repair_kw = ("repair", "fix", "bug", "patch", "issue", "pr ", "pull request", "bounty")
    build_kw = ("build", "create", "make", "implement", "scaffold", "generate", "write a")
    search_kw = ("search", "find", "look up", "list", "discover", "scan", "github")
    monitor_kw = ("monitor", "watch", "track", "status", "health", "report")

    if _is_explicit_search(lowered):
        intent = "search"
    elif any(k in lowered for k in repair_kw):
        intent = "repair"
    elif any(k in lowered for k in search_kw):
        intent = "search"
    elif any(k in lowered for k in build_kw):
        intent = "build"
    elif any(k in lowered for k in monitor_kw):
        intent = "monitor"
    else:
        intent = "unknown"

    return {
        "intent": intent,
        "target": text.strip()[:200],
        "parameters": {},
        "_fallback": True,
    }


def _is_explicit_search(lowered: str) -> bool:
    return (
        lowered.startswith(("search ", "find ", "look up ", "list ", "discover "))
        or "search github" in lowered
        or "find github" in lowered
        or "look up github" in lowered
    )


def _ollama_available() -> bool:
    try:
        import httpx
        response = httpx.get("http://127.0.0.1:11434/api/tags", timeout=2)
        return response.status_code == 200
    except Exception:
        return False


def _task_type_hint(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ("code", "function", "debug", "bug", "repair", "build", "write me a")):
        return "code"
    if any(word in lowered for word in ("image", "screenshot", "vision", "blueprint")):
        return "vision"
    if any(word in lowered for word in ("reason", "analyze", "math", "plan")):
        return "reason"
    if any(word in lowered for word in ("embed", "memory", "recall", "semantic")):
        return "embed"
    return "chat"


def parse_intent(
    text: str,
    *,
    model: Optional[str] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    """Parse a user request into a structured intent.

    Returns a dict shaped like::

        {
          "intent": "repair" | "build" | "search" | "monitor" | "unknown",
          "target": "<short description of the thing to act on>",
          "parameters": { ... freeform ... }
        }

    Uses Ollama with structured JSON output and temperature=0. Falls back to
    keyword classification if Ollama isn't reachable.
    """
    if not text or not str(text).strip():
        return {"intent": "unknown", "target": "", "parameters": {}}

    if not _ollama_available():
        return _parse_intent_keywords(text)

    try:
        import httpx
        selected_model = model or model_manager.get_model_for_task(_task_type_hint(text))

        system_prompt = (
            "You are SentinelAI's intent classifier. Given a user task, "
            "return ONLY a JSON object with these fields: "
            "'intent' (one of: repair, build, search, monitor, unknown), "
            "'target' (a short string describing the subject), "
            "'parameters' (an object with any extracted parameters). "
            "Return nothing but the JSON."
        )

        payload = {
            "model": selected_model,
            "prompt": (
                f"{system_prompt}\n\n"
                f"User task: {text.strip()}\n\n"
                "JSON response:"
            ),
            "format": "json",
            "stream": False,
            "options": {"temperature": 0},
        }
        response = httpx.post(
            "http://127.0.0.1:11434/api/generate",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        raw = data.get("response", "").strip()
        parsed = json.loads(raw)

        intent = str(parsed.get("intent", "unknown")).lower().strip()
        if intent not in VALID_INTENTS:
            intent = "unknown"
        if _is_explicit_search(text.lower()):
            intent = "search"

        return {
            "intent": intent,
            "target": str(parsed.get("target", text.strip()[:200]))[:500],
            "parameters": parsed.get("parameters") or {},
        }
    except Exception as exc:
        logger.warning("ollama parse_intent failed (%s) — using keyword fallback", exc)
        return _parse_intent_keywords(text)


# ─── Worker manager ───────────────────────────────────────────────────────────


class WorkerManager:
    """Resolves an intent to a concrete worker callable.

    Workers are looked up via the capability registry. The manager itself
    does not own the worker code — it just decides which existing function
    to invoke. The two built-in mappings are:

      - intent='search'   → scanner.run_scan (returns count of opportunities)
      - intent='repair'   → executor.run_executor
      - intent='build'    → returns ``needs_forge`` so the orchestrator
                            can request Forge approval.
      - intent='monitor'  → health/queue summary from db + qm.

    Custom tools built by Forge land in tools.registry with tool_type='built'
    and become available via :meth:`find_worker_for_description`.
    """

    def __init__(self):
        self._handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}
        self.register_handler("repair", self._handle_repair)
        self.register_handler("search", self._handle_search)
        self.register_handler("monitor", self._handle_monitor)

    def register_handler(
        self, intent: str, handler: Callable[[Dict[str, Any]], Dict[str, Any]]
    ) -> None:
        self._handlers[intent] = handler

    # ── public ───────────────────────────────────────────────────────────

    def dispatch(self, task_id: str, task_description: str) -> Dict[str, Any]:
        """Resolve task_description into a result dict.

        Result shape::

            {"worker": <str>, "status": "ok", "result": <dict>}
            {"needs_forge": True, "reason": "<str>"}
        """
        intent_info = parse_intent(task_description)
        intent = intent_info["intent"]

        # First: do we already have a tool that matches?
        tool_match = tool_registry.find_tool_for_task(task_description)

        if intent == "build":
            # build always goes via Forge — except if a previously-built
            # tool exactly matches the task description.
            if tool_match and tool_match.get("tool_type") == "built":
                return self._invoke_built_tool(tool_match, task_id, task_description)
            return {
                "needs_forge": True,
                "reason": "build intent — no existing tool matches",
                "intent": intent_info,
                "tool_match": tool_match,
            }

        # Other known intents → run the registered handler.
        if intent in self._handlers:
            try:
                result = self._handlers[intent]({
                    "task_id": task_id,
                    "task_description": task_description,
                    "intent": intent_info,
                })
                return {
                    "worker": intent,
                    "status": "ok",
                    "result": result,
                    "intent": intent_info,
                }
            except Exception as exc:
                logger.exception("worker '%s' raised", intent)
                return {
                    "worker": intent,
                    "status": "error",
                    "error": str(exc),
                    "intent": intent_info,
                }

        # Unknown intent — try the registry first; otherwise needs_forge.
        if tool_match:
            return self._invoke_built_tool(tool_match, task_id, task_description)

        return {
            "needs_forge": True,
            "reason": "no worker registered for intent and no tool matched",
            "intent": intent_info,
            "tool_match": None,
        }

    def get_worker_status(self) -> List[Dict[str, Any]]:
        """Return the public list of known workers (for /api/workers/status)."""
        try:
            import worker_manager as wm
            mgr = wm.get_manager()
            statuses = mgr.get_all_worker_status() if mgr.workers else []
        except Exception:
            statuses = []

        # Decorate with the orchestrator's logical workers.
        logical = []
        for intent, _ in self._handlers.items():
            logical.append({
                "worker_id": f"intent:{intent}",
                "intent": intent,
                "state": "idle",
                "last_run": None,
            })

        return {
            "logical_workers": logical,
            "pool_workers": statuses,
        }

    # ── default handlers ─────────────────────────────────────────────────

    def _handle_repair(self, task: Dict[str, Any]) -> Dict[str, Any]:
        try:
            executor = importlib.import_module("executor")
            result = executor.run_executor(dry_run=True)
            return {"executor_result": result, "dry_run": True}
        except Exception as exc:
            logger.warning("repair handler executor.run_executor failed: %s", exc)
            return {"executor_result": None, "error": str(exc)}

    def _handle_search(self, task: Dict[str, Any]) -> Dict[str, Any]:
        description = task.get("task_description", "")
        if any(word in description.lower() for word in ("github", "web", "search", "http")):
            try:
                from workers import web_worker
                result = web_worker.run_web_task(task.get("task_id", "search"), description)
                return {
                    "web_worker": result,
                    "opportunities_found": len(result.get("data") or []) if result.get("status") == "ok" else 0,
                }
            except Exception as exc:
                logger.warning("search handler web_worker failed: %s", exc)
        try:
            import asyncio
            scanner = importlib.import_module("scanner")
            count = asyncio.run(scanner.run_scan(dry_run=True))
            return {"opportunities_found": count}
        except Exception as exc:
            logger.warning("search handler scanner.run_scan failed: %s", exc)
            return {"opportunities_found": 0, "error": str(exc)}

    def _handle_monitor(self, task: Dict[str, Any]) -> Dict[str, Any]:
        try:
            counts = db.count_opportunities_by_status()
        except Exception:
            counts = {}
        try:
            earnings = db.get_earnings_summary()
        except Exception:
            earnings = {}
        try:
            queue = qm.get_queue_stats()
        except Exception:
            queue = {}
        return {
            "opportunities": counts,
            "earnings": earnings,
            "queue": queue,
        }

    def _invoke_built_tool(
        self, tool: Dict[str, Any], task_id: str, task_description: str
    ) -> Dict[str, Any]:
        """Best-effort: log that a previously-built tool would run.

        Built tools live on disk under tools/built/. We don't attempt to
        import-and-run arbitrary code here; we just confirm the match.
        """
        try:
            tool_registry.record_tool_use(tool["tool_name"])
        except Exception:
            pass
        return {
            "worker": "registry",
            "status": "ok",
            "result": {
                "matched_tool": tool["tool_name"],
                "entry_point": tool.get("entry_point"),
                "description": tool.get("description"),
            },
            "intent": {"intent": "build", "target": task_description, "parameters": {}},
        }


# ─── Orchestrator ─────────────────────────────────────────────────────────────


class Orchestrator:
    """Central brain. Sequential, persistent, approval-gated."""

    def __init__(self):
        ensure_orchestrator_table()
        self.worker_manager = WorkerManager()
        self.openclaw = get_openclaw()
        self.openclaw.set_orchestrator(self)
        self._lock = threading.RLock()
        self._queue_lock = threading.RLock()
        self.personality = self._load_personality()

    @staticmethod
    def _load_personality() -> Dict[str, Any]:
        """Load the active voice personality (Task 5). Never raises."""
        try:
            from models import setup_wizard
            return setup_wizard.get_personality()
        except Exception:
            return {"personality": "sentinel", "system_prompt": ""}

    # ── persistence helpers ──────────────────────────────────────────────

    def _persist_task(
        self,
        task_id: str,
        description: str,
        source: str,
        context: Dict[str, Any],
        status: str = "pending",
    ) -> None:
        ensure_orchestrator_table()
        with db.get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO orchestrator_tasks
                      (task_id, description, source, context_json, status,
                       created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, COALESCE(
                       (SELECT created_at FROM orchestrator_tasks WHERE task_id = ?),
                       ?), ?)""",
                (
                    task_id,
                    description,
                    source,
                    _serialize(context),
                    status,
                    task_id,
                    _now(),
                    _now(),
                ),
            )

    def _update_task(
        self,
        task_id: str,
        *,
        status: Optional[str] = None,
        intent: Optional[Dict[str, Any]] = None,
        worker: Optional[str] = None,
        approval_id: Optional[str] = None,
        result: Any = None,
        error: Optional[str] = None,
    ) -> None:
        ensure_orchestrator_table()
        fields = []
        values: List[Any] = []
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if intent is not None:
            fields.append("intent_json = ?")
            values.append(_serialize(intent))
        if worker is not None:
            fields.append("worker = ?")
            values.append(worker)
        if approval_id is not None:
            fields.append("approval_id = ?")
            values.append(approval_id)
        if result is not None:
            fields.append("result_json = ?")
            values.append(_serialize(result))
        if error is not None:
            fields.append("error = ?")
            values.append(error)
        if not fields:
            return
        fields.append("updated_at = ?")
        values.append(_now())
        values.append(task_id)

        with db.get_conn() as conn:
            conn.execute(
                f"UPDATE orchestrator_tasks SET {', '.join(fields)} WHERE task_id = ?",
                values,
            )

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        ensure_orchestrator_table()
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM orchestrator_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        if not row:
            return None
        record = dict(row)
        for key in ("context_json", "intent_json", "result_json"):
            raw = record.get(key)
            if raw:
                try:
                    record[key.replace("_json", "")] = json.loads(raw)
                except Exception:
                    record[key.replace("_json", "")] = raw
        return record

    def list_tasks(
        self, status: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        ensure_orchestrator_table()
        with db.get_conn() as conn:
            if status:
                rows = conn.execute(
                    """SELECT * FROM orchestrator_tasks
                        WHERE status = ?
                        ORDER BY created_at DESC LIMIT ?""",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM orchestrator_tasks
                        ORDER BY created_at DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def get_queue_status(self) -> Dict[str, Any]:
        ensure_orchestrator_table()
        with db.get_conn() as conn:
            rows = conn.execute(
                """SELECT status, COUNT(*) as cnt
                     FROM orchestrator_tasks
                    GROUP BY status"""
            ).fetchall()
            counts = {row["status"]: row["cnt"] for row in rows}
            recent = conn.execute(
                """SELECT task_id, description, status, worker, approval_id, created_at
                     FROM orchestrator_tasks
                    ORDER BY created_at DESC LIMIT 20"""
            ).fetchall()
        return {
            "counts": counts,
            "recent": [dict(r) for r in recent],
        }

    # ── intent parsing pass-through ──────────────────────────────────────

    def parse_intent(self, text: str) -> Dict[str, Any]:
        return parse_intent(text)

    # ── core flow ────────────────────────────────────────────────────────

    def process_task(
        self,
        task_id: str,
        task_description: str,
        source: str = "desktop",
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run a task end-to-end. Sequential, blocking, persistent."""
        context = dict(context or {})
        if not task_id:
            task_id = f"task-{uuid.uuid4().hex[:12]}"

        self._persist_task(task_id, task_description, source, context, status="running")

        try:
            intent_info = parse_intent(task_description)
            self._update_task(task_id, intent=intent_info)

            dispatch_result = self.worker_manager.dispatch(task_id, task_description)

            if dispatch_result.get("needs_forge"):
                return self._handle_forge_flow(
                    task_id=task_id,
                    task_description=task_description,
                    context=context,
                    intent=intent_info,
                    dispatch_result=dispatch_result,
                )

            self._update_task(
                task_id,
                worker=dispatch_result.get("worker"),
                status="completed",
                result=dispatch_result,
            )
            return {
                "task_id": task_id,
                "status": "completed",
                "intent": intent_info,
                "worker": dispatch_result.get("worker"),
                "result": dispatch_result.get("result"),
                "approval_id": None,
            }
        except Exception as exc:
            logger.exception("process_task crashed: %s", exc)
            self._update_task(task_id, status="failed", error=str(exc))
            return {
                "task_id": task_id,
                "status": "failed",
                "error": str(exc),
            }

    # ── forge flow ───────────────────────────────────────────────────────

    def _handle_forge_flow(
        self,
        *,
        task_id: str,
        task_description: str,
        context: Dict[str, Any],
        intent: Dict[str, Any],
        dispatch_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Forge approval gate. NO timeout auto-approval — ever."""
        forge_prompt = self._build_forge_prompt(task_description, intent, context)

        payload = {
            "task_id": task_id,
            "task_description": task_description,
            "intent": intent,
            "forge_prompt": forge_prompt,
        }

        approval_id = self.openclaw.request_approval(
            action_description=f"Forge will build: {task_description}",
            action_type="forge_start",
            payload=payload,
        )

        self._update_task(
            task_id,
            status="awaiting_approval",
            approval_id=approval_id,
            result={"reason": dispatch_result.get("reason"), "forge_prompt": forge_prompt},
        )

        # If the caller asked us to wait synchronously (default), block here.
        if context.get("wait_for_approval", True):
            final_status = self._wait_for_approval_blocking(approval_id, context)
            if final_status != "approved":
                self._update_task(task_id, status="denied", error=f"approval {final_status}")
                return {
                    "task_id": task_id,
                    "status": "denied",
                    "approval_id": approval_id,
                    "intent": intent,
                    "needs_forge": True,
                }
            return self._run_forge(
                task_id=task_id,
                approval_id=approval_id,
                forge_prompt=forge_prompt,
                intent=intent,
            )

        # Async — caller will poll & resume separately.
        return {
            "task_id": task_id,
            "status": "awaiting_approval",
            "approval_id": approval_id,
            "intent": intent,
            "needs_forge": True,
            "forge_prompt": forge_prompt,
        }

    def _wait_for_approval_blocking(
        self, approval_id: str, context: Dict[str, Any]
    ) -> str:
        """Poll the approval until it leaves 'pending'.

        ``context['approval_timeout']`` may set a *test-only* timeout. The
        production default is to wait forever — humans only.
        """
        timeout = context.get("approval_timeout")
        poll = float(context.get("approval_poll_interval", 1.0))
        return self.openclaw.wait_for_approval(
            approval_id, poll_interval=poll, timeout=timeout
        )

    def resume_approved_task(self, task_id: str) -> Dict[str, Any]:
        """Continue a task that was waiting on Forge approval.

        Call this after the user approves the gate when the original
        process_task() was launched with ``wait_for_approval=False``.
        """
        task = self.get_task(task_id)
        if not task:
            return {"status": "error", "error": "task not found"}
        approval_id = task.get("approval_id")
        if not approval_id:
            return {"status": "error", "error": "task has no approval_id"}
        if not self.openclaw.is_approved(approval_id):
            return {"status": "error", "error": "approval is not yet approved"}
        intent = task.get("intent") or {}
        forge_prompt = (task.get("result") or {}).get("forge_prompt", task.get("description"))
        return self._run_forge(task_id, approval_id, forge_prompt, intent)

    def _run_forge(
        self,
        task_id: str,
        approval_id: str,
        forge_prompt: str,
        intent: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not self.openclaw.is_approved(approval_id):
            raise RuntimeError(
                f"refusing to launch Forge — approval {approval_id} is not approved"
            )

        self._update_task(task_id, status="forging")

        try:
            from workers import forge_worker as fw
        except Exception as exc:
            self._update_task(task_id, status="failed", error=f"cannot import forge_worker: {exc}")
            return {
                "task_id": task_id,
                "status": "failed",
                "approval_id": approval_id,
                "error": f"forge_worker import failed: {exc}",
            }

        built_dir = Path.home() / "Desktop" / "SentinelAI" / "tools" / "built"
        try:
            built_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        try:
            result = fw.run_forge_task(
                task_id=task_id,
                workspace=str(built_dir),
                prompt=forge_prompt,
            )
        except Exception as exc:
            logger.exception("Forge run failed")
            self._update_task(task_id, status="failed", error=str(exc))
            return {
                "task_id": task_id,
                "status": "failed",
                "approval_id": approval_id,
                "error": str(exc),
            }

        # Register the newly built tool.
        output_path = str(result.get("output_path") or result.get("path") or built_dir)
        tool_name = f"forge_built_{task_id}"
        try:
            tool_registry.register_tool(
                tool_name,
                f"Forge-built for: {forge_prompt[:160]}",
                output_path,
                "built",
            )
        except Exception as exc:
            logger.warning("failed to register tool %s: %s", tool_name, exc)

        self._update_task(
            task_id,
            worker="forge",
            status="completed",
            result={"forge_result": result, "registered_tool": tool_name},
        )
        return {
            "task_id": task_id,
            "status": "completed",
            "approval_id": approval_id,
            "worker": "forge",
            "intent": intent,
            "result": {
                "forge_result": result,
                "registered_tool": tool_name,
                "output_path": output_path,
            },
        }

    def _build_forge_prompt(
        self,
        task_description: str,
        intent: Dict[str, Any],
        context: Dict[str, Any],
    ) -> str:
        target = intent.get("target") or task_description
        params = intent.get("parameters") or {}
        return (
            "You are Forge, SentinelAI's autonomous builder. Build a self-contained "
            "tool that fulfills the following request.\n\n"
            f"User request: {task_description}\n"
            f"Target: {target}\n"
            f"Parameters: {json.dumps(params, default=str)}\n\n"
            "Constraints:\n"
            "- The tool must be runnable from the SentinelAI workspace.\n"
            "- Prefer pure Python with a clear CLI entry point.\n"
            "- Write a short README.md alongside the tool.\n"
            "- Return JSON of {output_path, summary} when finished."
        )

    # ── crash-recovery helpers ───────────────────────────────────────────

    def recover_pending(self) -> int:
        """Re-mark in-flight tasks as 'pending' after a crash/restart.

        Tasks that were 'running' or 'forging' at crash time are reset to
        'pending' so the caller can re-process them. Tasks that were
        'awaiting_approval' are left alone — they still own a valid
        approval row.
        """
        ensure_orchestrator_table()
        with db.get_conn() as conn:
            cur = conn.execute(
                """UPDATE orchestrator_tasks
                      SET status = 'pending', updated_at = ?
                    WHERE status IN ('running', 'forging')""",
                (_now(),),
            )
        return cur.rowcount

    def process_pending(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Pop pending tasks and process them sequentially. Returns results."""
        ensure_orchestrator_table()
        out = []
        with self._queue_lock:
            with db.get_conn() as conn:
                rows = conn.execute(
                    """SELECT * FROM orchestrator_tasks
                        WHERE status = 'pending'
                        ORDER BY created_at ASC
                        LIMIT ?""",
                    (limit,),
                ).fetchall()
            pending = [dict(r) for r in rows]

        for row in pending:
            ctx = {}
            try:
                ctx = json.loads(row.get("context_json") or "{}")
            except Exception:
                pass
            result = self.process_task(
                task_id=row["task_id"],
                task_description=row["description"],
                source=row.get("source") or "desktop",
                context=ctx,
            )
            out.append(result)
        return out


# ─── Singleton ────────────────────────────────────────────────────────────────

_orchestrator: Optional[Orchestrator] = None
_orchestrator_lock = threading.Lock()


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        with _orchestrator_lock:
            if _orchestrator is None:
                _orchestrator = Orchestrator()
    return _orchestrator


def initialize_orchestrator() -> Orchestrator:
    orch = get_orchestrator()
    try:
        recovered = orch.recover_pending()
        if recovered:
            logger.info("orchestrator recovered %d pending tasks", recovered)
    except Exception as exc:
        logger.warning("orchestrator recover_pending failed: %s", exc)
    return orch


# ─── Module API ───────────────────────────────────────────────────────────────


def process_task(
    task_id: str,
    task_description: str,
    source: str = "desktop",
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return get_orchestrator().process_task(task_id, task_description, source, context)
