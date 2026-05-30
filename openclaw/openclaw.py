"""OpenClaw — the face of SentinelAI.

OpenClaw owns three responsibilities:

1. **Inbox** — receive_message() routes user messages (desktop / phone / api)
   to the orchestrator and returns a structured response.

2. **Notifications** — send_notification() pushes notices to the user
   (via the existing ntfy.sh integration when configured).

3. **Approval gate** — request_approval() persists a pending approval row
   to ``sentinelai.db``. ``forge_start`` and other privileged actions MUST
   wait for the human to call resolve_approval(approved=True) before they
   may proceed. **No timeout auto-approval. Ever.**

The approval table is created lazily on import via ensure_approvals_table().
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import db
import notifications

logger = logging.getLogger(__name__)


# ─── Schema ───────────────────────────────────────────────────────────────────

APPROVALS_SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    id            TEXT PRIMARY KEY,
    action_type   TEXT NOT NULL,
    description   TEXT NOT NULL,
    payload       TEXT DEFAULT '{}',
    status        TEXT NOT NULL DEFAULT 'pending',
    created_at    TEXT NOT NULL,
    resolved_at   TEXT,
    resolved_by   TEXT,
    reason        TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
CREATE INDEX IF NOT EXISTS idx_approvals_action_type ON approvals(action_type);
"""


_schema_lock = threading.Lock()
_schema_initialized = False


def ensure_approvals_table() -> None:
    """Create the approvals table if it does not exist. Idempotent."""
    global _schema_initialized
    if _schema_initialized:
        return
    with _schema_lock:
        if _schema_initialized:
            return
        with db.get_conn() as conn:
            conn.executescript(APPROVALS_SCHEMA)
        _schema_initialized = True


# ─── Errors ───────────────────────────────────────────────────────────────────


class ApprovalNotFoundError(KeyError):
    """Raised when a requested approval_id cannot be found."""


class DuplicateApprovalError(RuntimeError):
    """Raised when an identical pending approval already exists."""

    def __init__(self, message: str, existing_id: str):
        super().__init__(message)
        self.existing_id = existing_id


# ─── Constants ────────────────────────────────────────────────────────────────

VALID_ACTION_TYPES = {
    "forge_start",
    "pr_submit",
    "file_delete",
    "financial",
}

VALID_SOURCES = {"desktop", "phone", "api"}

VALID_PRIORITIES = {"low", "normal", "high", "urgent"}


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.utcnow().isoformat()


def _row_to_dict(row) -> Dict[str, Any]:
    record = dict(row)
    if record.get("payload"):
        try:
            record["payload"] = json.loads(record["payload"])
        except (TypeError, ValueError):
            record["payload"] = {}
    else:
        record["payload"] = {}
    return record


def _find_duplicate_pending(action_type: str, payload_json: str) -> Optional[Dict[str, Any]]:
    """Return an existing pending approval with the same action_type+payload."""
    with db.get_conn() as conn:
        row = conn.execute(
            """SELECT * FROM approvals
                WHERE status = 'pending'
                  AND action_type = ?
                  AND payload = ?
                ORDER BY created_at ASC
                LIMIT 1""",
            (action_type, payload_json),
        ).fetchone()
        return _row_to_dict(row) if row else None


# ─── OpenClaw class ───────────────────────────────────────────────────────────


class OpenClaw:
    """Central message handler & approval gate.

    Held as a singleton via :func:`get_openclaw`. The orchestrator and Flask
    layer both work through the same instance.
    """

    def __init__(self):
        ensure_approvals_table()
        self._orchestrator = None
        self._lock = threading.RLock()
        self._notification_handlers: List[Any] = []

    # ─── Wiring ───────────────────────────────────────────────────────────

    def set_orchestrator(self, orchestrator: Any) -> None:
        """Inject the orchestrator (avoids a circular import)."""
        self._orchestrator = orchestrator

    def get_orchestrator(self) -> Any:
        return self._orchestrator

    # ─── Messages ─────────────────────────────────────────────────────────

    def receive_message(
        self,
        source: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Route a user message to the orchestrator.

        Returns a structured response. If no orchestrator is wired, the
        message is logged and a stub reply is returned (handy for tests).
        """
        if source not in VALID_SOURCES:
            return {
                "status": "error",
                "error": f"invalid source '{source}'. Expected one of {sorted(VALID_SOURCES)}",
            }
        if not message or not str(message).strip():
            return {"status": "error", "error": "message is required"}

        ctx = dict(context or {})
        ctx.setdefault("source", source)

        try:
            db.log_event(
                "openclaw_message",
                f"[{source}] {str(message)[:300]}",
            )
        except Exception:
            pass

        # Personal-assistant (MCP) intents — handled directly when read-only /
        # reversible; irreversible actions are routed through the approval gate.
        mcp_result = self._try_mcp_intent(str(message))
        if mcp_result is not None:
            return mcp_result

        if self._orchestrator is None:
            logger.warning("OpenClaw received message with no orchestrator wired")
            return {
                "status": "queued",
                "data": {
                    "message": message,
                    "source": source,
                    "note": "orchestrator not yet wired — message logged only",
                },
                "error": None,
            }

        try:
            task_id = ctx.get("task_id") or f"task-{uuid.uuid4().hex[:12]}"
            result = self._orchestrator.process_task(
                task_id=task_id,
                task_description=str(message),
                source=source,
                context=ctx,
            )
            return {"status": "ok", "data": result, "error": None}
        except Exception as exc:
            logger.exception("orchestrator.process_task failed")
            return {"status": "error", "data": None, "error": str(exc)}

    def _try_mcp_intent(self, message: str) -> Optional[Dict[str, Any]]:
        """Parse simple personal-assistant commands. Returns a response dict
        when an MCP intent matches, else None (so normal routing continues).

        Read-only / reversible actions execute immediately. Irreversible ones
        (write/delete) create an approval gate and return awaiting_approval.
        """
        text = message.strip()
        low = text.lower()
        try:
            from openclaw import mcp_tools
        except Exception:
            return None

        def reply(action, result, orb_state="speaking"):
            ok = bool(result and result.get("ok"))
            return {
                "status": "ok" if ok else "error",
                "data": {
                    "handler": "mcp",
                    "action": action,
                    "result": result,
                    "response": result.get("error") if not ok else f"{action} done.",
                    "orb_state": orb_state,
                },
                "error": None if ok else (result or {}).get("error"),
            }

        if low.startswith("open ") and not low.startswith("open file"):
            target = text[5:].strip()
            if target.startswith(("http://", "https://", "www.")):
                return reply("open_url", mcp_tools.open_url(target))
            return reply("open_app", mcp_tools.open_app(target))

        if "take screenshot" in low or low == "screenshot":
            res = mcp_tools.take_screenshot()
            # don't dump the base64 into the response text
            trimmed = {"ok": res.get("ok"), "format": (res.get("data") or {}).get("format"),
                       "size": (res.get("data") or {}).get("size"), "error": res.get("error")}
            out = reply("take_screenshot", res)
            out["data"]["result"] = trimmed
            return out

        if low.startswith("search for "):
            return reply("web_search", mcp_tools.web_search_quick(text[11:].strip()))
        if low.startswith("search the web for "):
            return reply("web_search", mcp_tools.web_search_quick(text[19:].strip()))

        if low.startswith("read file "):
            return reply("read_file", mcp_tools.read_file(text[10:].strip()))
        if low.startswith("list directory ") or low.startswith("list folder "):
            path = text.split(" ", 2)[2].strip()
            return reply("list_directory", mcp_tools.list_directory(path))

        # IRREVERSIBLE — gate behind approval, never execute here.
        if low.startswith("delete file ") or low.startswith("write file "):
            action = "file_delete"
            approval_id = self.request_approval(
                action_description=text,
                action_type=action,
                payload={"command": text},
            )
            return {
                "status": "ok",
                "data": {
                    "handler": "mcp",
                    "action": action,
                    "status": "awaiting_approval",
                    "approval_id": approval_id,
                    "response": "That is an irreversible action — it needs your approval.",
                    "orb_state": "alert",
                },
                "error": None,
            }

        return None

    # ─── Notifications ────────────────────────────────────────────────────

    def send_notification(
        self,
        message: str,
        priority: str = "normal",
        requires_approval: bool = False,
        title: str = "SentinelAI",
    ) -> str:
        """Send a notification to the user.

        Returns the notification_id (a uuid). If an approval is required,
        the caller should *also* call :meth:`request_approval` — this method
        only delivers the notice.
        """
        if priority not in VALID_PRIORITIES:
            priority = "normal"

        notification_id = f"notif-{uuid.uuid4().hex[:12]}"

        # Map our priority labels onto ntfy.sh priorities.
        ntfy_priority = {
            "low": "low",
            "normal": "default",
            "high": "high",
            "urgent": "urgent",
        }[priority]

        try:
            notifications.send_notification(
                title=title,
                message=str(message),
                priority=ntfy_priority,
                tags="warning" if requires_approval else "robot",
            )
        except Exception as exc:
            logger.warning("send_notification failed: %s", exc)

        try:
            db.log_event(
                "openclaw_notification",
                f"[{priority}] {str(message)[:300]} requires_approval={requires_approval}",
            )
        except Exception:
            pass

        return notification_id

    # ─── Approvals ────────────────────────────────────────────────────────

    def request_approval(
        self,
        action_description: str,
        action_type: str,
        payload: Optional[Dict[str, Any]] = None,
        raise_on_duplicate: bool = False,
    ) -> str:
        """Create a pending approval row. Returns the approval id.

        If a pending approval already exists for the same action_type+payload,
        the existing id is returned (or a DuplicateApprovalError is raised
        when ``raise_on_duplicate`` is True).
        """
        if action_type not in VALID_ACTION_TYPES:
            raise ValueError(
                f"unknown action_type '{action_type}'. Expected one of {sorted(VALID_ACTION_TYPES)}"
            )
        if not action_description or not str(action_description).strip():
            raise ValueError("action_description is required")

        payload_json = json.dumps(payload or {}, sort_keys=True, default=str)

        with self._lock:
            ensure_approvals_table()

            existing = _find_duplicate_pending(action_type, payload_json)
            if existing:
                logger.info(
                    "request_approval: returning existing pending approval %s",
                    existing["id"],
                )
                if raise_on_duplicate:
                    raise DuplicateApprovalError(
                        f"pending approval already exists for {action_type}",
                        existing_id=existing["id"],
                    )
                return existing["id"]

            approval_id = f"appr-{uuid.uuid4().hex[:12]}"
            with db.get_conn() as conn:
                conn.execute(
                    """INSERT INTO approvals
                          (id, action_type, description, payload, status, created_at)
                       VALUES (?, ?, ?, ?, 'pending', ?)""",
                    (
                        approval_id,
                        action_type,
                        str(action_description),
                        payload_json,
                        _now(),
                    ),
                )

            try:
                db.log_event(
                    "approval_requested",
                    f"[{action_type}] {action_description[:200]} ({approval_id})",
                )
            except Exception:
                pass

            self.send_notification(
                message=f"Approval required: {action_description}",
                priority="high",
                requires_approval=True,
            )

            return approval_id

    def get_pending_approvals(self) -> List[Dict[str, Any]]:
        ensure_approvals_table()
        with db.get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM approvals
                    WHERE status = 'pending'
                    ORDER BY created_at ASC"""
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def get_approval(self, approval_id: str) -> Optional[Dict[str, Any]]:
        ensure_approvals_table()
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM approvals WHERE id = ?", (approval_id,)
            ).fetchone()
        return _row_to_dict(row) if row else None

    def resolve_approval(
        self,
        approval_id: str,
        approved: bool,
        reason: str = "",
        resolved_by: str = "user",
    ) -> bool:
        """Resolve a pending approval. Returns True on success.

        Raises :class:`ApprovalNotFoundError` if the id is unknown. If the
        approval has already been resolved, the call is a no-op and returns
        False.
        """
        ensure_approvals_table()
        with self._lock:
            with db.get_conn() as conn:
                row = conn.execute(
                    "SELECT * FROM approvals WHERE id = ?", (approval_id,)
                ).fetchone()
                if row is None:
                    raise ApprovalNotFoundError(f"unknown approval_id: {approval_id}")

                current_status = row["status"]
                if current_status != "pending":
                    logger.info(
                        "resolve_approval: %s already %s — no-op",
                        approval_id,
                        current_status,
                    )
                    return False

                new_status = "approved" if approved else "denied"
                conn.execute(
                    """UPDATE approvals
                          SET status = ?, resolved_at = ?, resolved_by = ?, reason = ?
                        WHERE id = ?""",
                    (new_status, _now(), resolved_by, str(reason or ""), approval_id),
                )

            try:
                db.log_event(
                    "approval_resolved",
                    f"[{row['action_type']}] {approval_id} -> {new_status} by {resolved_by}",
                )
            except Exception:
                pass
            return True

    def is_approved(self, approval_id: str) -> bool:
        approval = self.get_approval(approval_id)
        return bool(approval and approval.get("status") == "approved")

    def wait_for_approval(
        self,
        approval_id: str,
        poll_interval: float = 1.0,
        timeout: Optional[float] = None,
    ) -> str:
        """Block until the approval reaches a terminal state.

        Returns the final status ('approved' or 'denied'). If timeout is None,
        waits indefinitely (HARD RULE: forge_start must never auto-approve).
        """
        import time

        start = time.time()
        while True:
            approval = self.get_approval(approval_id)
            if approval is None:
                raise ApprovalNotFoundError(approval_id)
            status = approval.get("status", "pending")
            if status != "pending":
                return status
            if timeout is not None and (time.time() - start) > timeout:
                return "pending"
            time.sleep(poll_interval)


# ─── Singleton ────────────────────────────────────────────────────────────────

_instance: Optional[OpenClaw] = None
_instance_lock = threading.Lock()


def get_openclaw() -> OpenClaw:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = OpenClaw()
    return _instance


# ─── Module-level helpers (the spec API) ──────────────────────────────────────


def receive_message(
    source: str,
    message: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return get_openclaw().receive_message(source, message, context)


def send_notification(
    message: str,
    priority: str = "normal",
    requires_approval: bool = False,
) -> str:
    return get_openclaw().send_notification(message, priority, requires_approval)


def request_approval(
    action_description: str,
    action_type: str,
    payload: Optional[Dict[str, Any]] = None,
) -> str:
    return get_openclaw().request_approval(action_description, action_type, payload)


def get_pending_approvals() -> List[Dict[str, Any]]:
    return get_openclaw().get_pending_approvals()


def resolve_approval(approval_id: str, approved: bool, reason: str = "") -> bool:
    return get_openclaw().resolve_approval(approval_id, approved, reason)


def is_approved(approval_id: str) -> bool:
    return get_openclaw().is_approved(approval_id)
