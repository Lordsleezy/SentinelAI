"""OpenClaw integration layer for SentinelAI.

OpenClaw is the user-facing message handler and approval gate.
It receives messages from desktop / phone / api sources, routes them to
the orchestrator, and persists every approval request to sentinelai.db.
"""

from .openclaw import (
    OpenClaw,
    get_openclaw,
    receive_message,
    send_notification,
    request_approval,
    get_pending_approvals,
    resolve_approval,
    is_approved,
    ensure_approvals_table,
    ApprovalNotFoundError,
    DuplicateApprovalError,
)

__all__ = [
    "OpenClaw",
    "get_openclaw",
    "receive_message",
    "send_notification",
    "request_approval",
    "get_pending_approvals",
    "resolve_approval",
    "is_approved",
    "ensure_approvals_table",
    "ApprovalNotFoundError",
    "DuplicateApprovalError",
]
