"""
workers/sync/conversation_sync.py
Pulls conversation history from Claude.ai and ChatGPT via browser automation.
Runs on a 60-minute schedule. Processes new conversations through memory pipeline.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from workers.identity.browser_sessions import BrowserSessions

logger = logging.getLogger(__name__)

_SYNC_STATE_PATH = Path(__file__).parent.parent.parent / "memory" / "vault" / "sync_state.json"
_CONVOS_PATH = Path(__file__).parent.parent.parent / "memory" / "vault" / "conversations"


@dataclass
class Conversation:
    platform: str            # "claude" | "chatgpt"
    title: str
    date: str
    messages: List[dict] = field(default_factory=list)  # [{"role": "user"|"assistant", "content": str}]
    url: str = ""
    synced_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    conv_id: str = ""

    def to_dict(self):
        return asdict(self)


class ConversationSync:
    """
    Pulls conversation history from Claude.ai and ChatGPT.
    Runs on APScheduler. Processes new conversations through memory pipeline.
    """

    def __init__(self, sessions: Optional["BrowserSessions"] = None,
                 socketio=None):
        self.sessions = sessions
        self.socketio = socketio
        self.last_sync: dict = {}
        self.conversations_synced: int = 0
        self._load_state()
        _CONVOS_PATH.mkdir(parents=True, exist_ok=True)

    def _log(self, msg: str, level: str = "info"):
        logger.info("[Sync] %s", msg)
        if self.socketio:
            try:
                self.socketio.emit("log_event", {
                    "type": "sync", "level": level,
                    "message": msg, "timestamp": datetime.now().isoformat()
                })
            except Exception:
                pass

    def _load_state(self):
        try:
            if _SYNC_STATE_PATH.exists():
                state = json.loads(_SYNC_STATE_PATH.read_text(encoding="utf-8"))
                self.last_sync = state.get("last_sync", {})
                self.conversations_synced = state.get("conversations_synced", 0)
        except Exception:
            pass

    def _save_state(self):
        try:
            _SYNC_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _SYNC_STATE_PATH.write_text(
                json.dumps({
                    "last_sync": self.last_sync,
                    "conversations_synced": self.conversations_synced,
                }, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("[Sync] State save failed: %s", e)

    def sync_all(self):
        """Pull from both platforms. Called by APScheduler."""
        self._log("Starting conversation sync...")
        synced = 0
        synced += self._sync_platform("claude")
        synced += self._sync_platform("chatgpt")
        self.conversations_synced += synced
        self._save_state()
        self._log(f"Sync complete: {synced} new conversations", "success")

    def _sync_platform(self, platform: str) -> int:
        """Sync one platform. Returns count of new conversations processed."""
        if not self.sessions:
            self._log(f"No browser sessions — skipping {platform} sync", "info")
            return 0

        try:
            import asyncio
            loop = asyncio.new_event_loop()
            convos = loop.run_until_complete(self._extract_conversations_async(platform))
        except Exception as e:
            self._log(f"Sync error for {platform}: {e}", "error")
            return 0

        if not convos:
            return 0

        new_count = 0
        for conv in convos:
            if self._is_new(conv):
                self._save_conversation(conv)
                self._process_into_memory(conv)
                new_count += 1

        self.last_sync[platform] = datetime.now(timezone.utc).isoformat()
        self._log(f"{platform}: {new_count} new conversations synced")
        return new_count

    def _is_new(self, conv: Conversation) -> bool:
        """Check if this conversation was already synced."""
        last = self.last_sync.get(conv.platform)
        if not last:
            return True
        try:
            return conv.date > last
        except Exception:
            return True

    def _save_conversation(self, conv: Conversation):
        """Save conversation JSON to vault."""
        safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in conv.title)[:60]
        filename = f"{conv.platform}_{conv.date[:10]}_{safe_title}.json"
        path = _CONVOS_PATH / filename
        path.write_text(json.dumps(conv.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def _process_into_memory(self, conv: Conversation):
        """Process conversation through memory pipeline."""
        try:
            from memory_manager import get_memory_manager
            mm = get_memory_manager()
            content = f"[{conv.platform}] {conv.title}\n" + "\n".join(
                f"{m['role']}: {m['content'][:500]}"
                for m in conv.messages[:10]
            )
            mm.write_session({
                "platform": conv.platform,
                "title": conv.title,
                "content": content,
                "date": conv.date,
                "source": conv.platform,
            })
        except Exception as e:
            logger.debug("[Sync] Memory processing failed: %s", e)

    async def _extract_conversations_async(self, platform: str) -> List[Conversation]:
        """Use Playwright to extract conversation list from the platform."""
        if platform == "claude":
            return await self._extract_claude_async()
        elif platform == "chatgpt":
            return await self._extract_chatgpt_async()
        return []

    async def _extract_claude_async(self) -> List[Conversation]:
        """Navigate claude.ai conversation history and extract metadata."""
        convos = []
        try:
            ctx = await self.sessions._get_context()
            stealth = self.sessions._stealth
            page = await stealth.new_page(ctx)
            await page.goto("https://claude.ai/chats", wait_until="domcontentloaded")
            import asyncio as _asyncio
            await _asyncio.sleep(2)

            # Extract conversation list items
            links = await page.query_selector_all('a[href*="/chat/"]')
            for link in links[:20]:
                try:
                    title = await link.inner_text()
                    href = await link.get_attribute("href")
                    if title and href:
                        convos.append(Conversation(
                            platform="claude",
                            title=title.strip()[:200],
                            date=datetime.now(timezone.utc).isoformat(),
                            url=f"https://claude.ai{href}" if href.startswith("/") else href,
                        ))
                except Exception:
                    continue

            await page.close()
        except Exception as e:
            logger.debug("[Sync] Claude extraction failed: %s", e)
        return convos

    async def _extract_chatgpt_async(self) -> List[Conversation]:
        """Navigate chatgpt.com conversation history and extract metadata."""
        convos = []
        try:
            ctx = await self.sessions._get_context()
            stealth = self.sessions._stealth
            page = await stealth.new_page(ctx)
            await page.goto("https://chatgpt.com", wait_until="domcontentloaded")
            import asyncio as _asyncio
            await _asyncio.sleep(2)

            links = await page.query_selector_all('a[href*="/c/"]')
            for link in links[:20]:
                try:
                    title = await link.inner_text()
                    href = await link.get_attribute("href")
                    if title and href:
                        convos.append(Conversation(
                            platform="chatgpt",
                            title=title.strip()[:200],
                            date=datetime.now(timezone.utc).isoformat(),
                            url=f"https://chatgpt.com{href}" if href.startswith("/") else href,
                        ))
                except Exception:
                    continue

            await page.close()
        except Exception as e:
            logger.debug("[Sync] ChatGPT extraction failed: %s", e)
        return convos

    def get_all_conversations(self) -> List[dict]:
        """Return list of all synced conversations from disk."""
        convos = []
        try:
            for f in sorted(_CONVOS_PATH.glob("*.json"), reverse=True)[:100]:
                try:
                    convos.append(json.loads(f.read_text(encoding="utf-8")))
                except Exception:
                    pass
        except Exception:
            pass
        return convos

    def get_status(self) -> dict:
        """Return sync status for /sync/status endpoint."""
        from datetime import timedelta
        next_sync_seconds = 3600
        if self.last_sync:
            last = max(self.last_sync.values())
            try:
                last_dt = datetime.fromisoformat(last)
                elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
                next_sync_seconds = max(0, 3600 - elapsed)
            except Exception:
                pass

        mins = int(next_sync_seconds // 60)
        return {
            "last_sync_claude": self.last_sync.get("claude", "never"),
            "last_sync_chatgpt": self.last_sync.get("chatgpt", "never"),
            "conversations_synced": self.conversations_synced,
            "next_sync_in": f"{mins} minutes",
        }


# Singleton
_sync_instance: Optional[ConversationSync] = None


def get_conversation_sync(sessions=None, socketio=None) -> ConversationSync:
    global _sync_instance
    if _sync_instance is None:
        _sync_instance = ConversationSync(sessions=sessions, socketio=socketio)
    return _sync_instance
