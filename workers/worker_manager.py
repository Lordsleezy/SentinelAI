from __future__ import annotations

import logging
from typing import Dict, Optional

from tools import registry
from workers import web_worker

logger = logging.getLogger(__name__)


def _result(status: str, task_id: str, data=None, error: Optional[str] = None) -> Dict:
    return {"status": status, "task_id": task_id, "data": data, "error": error}


def dispatch(task_id, task_description, context=None) -> Dict:
    context = context or {}
    registry.register_builtin_tools()
    tool = registry.find_tool_for_task(task_description)
    if not tool:
        return {
            "status": "needs_forge",
            "task_id": task_id,
            "data": None,
            "error": None,
            "suggested_prompt": f"Build a SentinelAI capability for: {task_description}",
        }

    name = tool["tool_name"]
    registry.record_tool_use(name)
    if name == "web_search":
        return web_worker.run_web_task(task_id, task_description)
    if name == "repair":
        return _result("ok", task_id, {"worker": "repair", "task_description": task_description, "context": context}, None)
    if name == "forge":
        return {
            "status": "needs_forge",
            "task_id": task_id,
            "data": None,
            "error": None,
            "suggested_prompt": f"Forge approval required for: {task_description}",
        }
    return _result("error", task_id, None, f"No dispatcher for tool: {name}")


def get_worker_status() -> Dict:
    tools = registry.list_tools()
    return {
        "status": "ok",
        "registered_workers": len(tools),
        "workers": [{"tool_name": tool["tool_name"], "use_count": tool.get("use_count", 0)} for tool in tools],
    }


def list_available_workers():
    registry.register_builtin_tools()
    return registry.list_tools()


# ─── Repair routing (Task 7) ──────────────────────────────────────────────────
# Route repair work to the best engine:
#   complexity > 0.6  -> OpenHands (capable, slower)
#   complexity <= 0.6 -> Aider     (fast, cheap, local Ollama)
#   if the chosen engine is unavailable -> fall back to the built-in executor.
# Win rates per engine are tracked in DB and bias routing over time.

COMPLEXITY_THRESHOLD = 0.6
_WORKER_OUTCOMES_SCHEMA = """
CREATE TABLE IF NOT EXISTS worker_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker TEXT NOT NULL,
    success INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""


def complexity_score(issue: Dict) -> float:
    """0..1 complexity estimate. Higher = more complex.

    Simple (low score): single file, clear error message, has tests.
    Complex (high score): multi-file, architectural, no tests.
    """
    issue = issue or {}
    text = " ".join(str(issue.get(k, "")) for k in ("title", "body")).lower()
    labels = " ".join(issue.get("labels", []) or []).lower()
    score = 0.35  # neutral baseline

    files = issue.get("files_changed") or issue.get("files") or []
    if isinstance(files, list) and len(files) > 1:
        score += 0.25
    if any(w in (text + labels) for w in ("refactor", "architecture", "redesign", "rewrite", "multiple", "design")):
        score += 0.25
    if not issue.get("has_tests"):
        score += 0.15
    # clear, contained signals reduce complexity
    if any(w in text for w in ("typo", "docs", "readme", "rename", "lint", "one line", "single file")):
        score -= 0.25
    if issue.get("has_tests"):
        score -= 0.1
    if any(w in text for w in ("traceback", "stacktrace", "error:", "exception")):
        score -= 0.1  # a clear error message makes it more tractable
    return max(0.0, min(1.0, round(score, 4)))


def _ensure_outcomes_table():
    try:
        import db
        with db.get_conn() as conn:
            conn.executescript(_WORKER_OUTCOMES_SCHEMA)
    except Exception as exc:
        logger.debug("worker_outcomes table init skipped: %s", exc)


def record_worker_outcome(worker: str, success: bool) -> None:
    _ensure_outcomes_table()
    try:
        import db
        from datetime import datetime
        with db.get_conn() as conn:
            conn.execute(
                "INSERT INTO worker_outcomes (worker, success, created_at) VALUES (?, ?, ?)",
                (worker, 1 if success else 0, datetime.utcnow().isoformat()),
            )
    except Exception as exc:
        logger.debug("record_worker_outcome failed: %s", exc)


def worker_win_rate(worker: str) -> Optional[float]:
    _ensure_outcomes_table()
    try:
        import db
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT AVG(success) AS rate, COUNT(*) AS n FROM worker_outcomes WHERE worker = ?",
                (worker,),
            ).fetchone()
        if row and row["n"]:
            return float(row["rate"])
    except Exception:
        pass
    return None


def choose_repair_worker(issue: Dict) -> str:
    """Return 'openhands' | 'aider' | 'executor' for the given issue."""
    from workers import aider_worker, openhands_worker

    score = complexity_score(issue)
    prefer_complex = score > COMPLEXITY_THRESHOLD

    # Bias by historical win rate when we have enough signal.
    oh_rate = worker_win_rate("openhands")
    ai_rate = worker_win_rate("aider")
    if oh_rate is not None and ai_rate is not None and abs(oh_rate - ai_rate) > 0.25:
        prefer_complex = oh_rate > ai_rate

    if prefer_complex and openhands_worker.is_available():
        return "openhands"
    if aider_worker.is_available():
        return "aider"
    if openhands_worker.is_available():
        return "openhands"
    return "executor"  # built-in fallback always available


def route_repair(issue: Dict, repo_path: str = "") -> Dict:
    """Dispatch a repair to the selected engine, with graceful fallback.

    Returns the engine's standard result dict augmented with routing metadata.
    Does NOT raise — the built-in executor is the always-available fallback.
    """
    from workers import aider_worker, openhands_worker

    issue = issue or {}
    score = complexity_score(issue)
    choice = choose_repair_worker(issue)
    meta = {"routed_to": choice, "complexity": score}

    try:
        if choice == "openhands":
            res = openhands_worker.run_openhands_repair(issue.get("url", ""), repo_path)
        elif choice == "aider":
            res = aider_worker.run_aider_repair(
                issue.get("title", "") + "\n\n" + (issue.get("body", "") or ""), repo_path)
        else:
            res = {"worker": "executor", "status": "deferred",
                   "summary": "routed to built-in repair executor", "error": None}

        # If the chosen capable engine was unavailable, fall back.
        if res.get("status") == "unavailable" and choice != "executor":
            logger.info("repair engine %s unavailable — falling back to executor", choice)
            meta["fallback"] = "executor"
            res = {"worker": "executor", "status": "deferred",
                   "summary": f"{choice} unavailable; built-in executor will handle it",
                   "error": None}

        if res.get("status") in ("completed", "failed"):
            record_worker_outcome(res.get("worker", choice), res.get("status") == "completed")
        res.update(meta)
        return res
    except Exception as exc:
        logger.exception("route_repair failed")
        return {"worker": "executor", "status": "error", "error": str(exc), **meta}
