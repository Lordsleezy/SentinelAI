"""
Provider sync status — honest connection vs import vs sync state for Memory UI.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_STATES = (
    "OFFLINE", "AUTHENTICATING", "AUTHENTICATED",
    "IMPORTING", "SYNCING", "SYNCED", "FAILED",
)


def _count_memories_by_source(source: str) -> int:
    try:
        from workers.memory.memory_manager_v2 import get_memory_manager_v2
        mm = get_memory_manager_v2()
        stats = mm.get_stats()
        by = stats.get("by_source") or stats.get("sources") or {}
        if isinstance(by, dict):
            return int(by.get(source, 0) or by.get(source.lower(), 0))
    except Exception:
        pass
    return 0


def _count_vault_conversations(platform: str) -> int:
    root = Path(__file__).resolve().parents[2] / "memory" / "vault" / "conversations"
    if not root.is_dir():
        return 0
    return len(list(root.glob(f"{platform}_*.json")))


def get_provider_sync_status(
    login_status: Optional[Dict[str, Any]] = None,
    sync_status: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build per-provider status for Memory panel.
    Connected != Synced — separate authentication from import counts.
    """
    login_status = login_status or {}
    sync_status = sync_status or {}

    providers: List[Dict[str, Any]] = []
    for platform, label in (("claude", "Claude"), ("chatgpt", "ChatGPT")):
        connected = bool(login_status.get(f"{platform}_connected"))
        creds = bool(login_status.get(f"{platform}_creds_saved"))
        last_sync = sync_status.get(f"last_sync_{platform}", "never")
        imported_files = _count_vault_conversations(platform)
        memory_count = _count_memories_by_source(platform)

        if connected and memory_count > 0 and last_sync not in ("never", "", None):
            state = "SYNCED"
        elif connected and imported_files > 0:
            state = "AUTHENTICATED"
        elif connected:
            state = "AUTHENTICATED"
        elif creds:
            state = "OFFLINE"
        else:
            state = "OFFLINE"

        if last_sync == "never" and connected:
            state = "AUTHENTICATED"

        providers.append({
            "provider": label,
            "platform": platform,
            "state": state,
            "authenticated": connected,
            "credentials_saved": creds,
            "imported_conversations": imported_files,
            "memory_count": memory_count,
            "last_sync": last_sync,
            "errors": [],
            "session_age": login_status.get(f"{platform}_session_age", ""),
        })

    return {
        "providers": providers,
        "conversations_synced_total": sync_status.get("conversations_synced", 0),
        "next_sync_in": sync_status.get("next_sync_in", ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
