"""
workers/identity/thread_manager.py
Manages conversation threads on Claude.ai and ChatGPT.
Tracks which threads exist, reuses them per topic/project,
and creates new ones for new topics.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

_REGISTRY_PATH = Path(__file__).parent.parent.parent / "memory" / "vault" / "threads" / "registry.json"


@dataclass
class ConversationThread:
    thread_id: str
    platform: str          # "claude" | "chatgpt"
    topic: str
    project: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_used: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    url: Optional[str] = None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ConversationThread":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class ThreadManager:
    """
    Tracks conversation threads on each platform.
    Reuses threads for the same topic/project.
    Creates new threads for new topics.
    Registry saved to memory/vault/threads/registry.json
    """

    THREAD_MAX_AGE_DAYS = 7

    def __init__(self):
        _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._threads: List[ConversationThread] = []
        self._load()

    def _load(self):
        try:
            if _REGISTRY_PATH.exists():
                data = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
                self._threads = [ConversationThread.from_dict(t) for t in data.get("threads", [])]
        except Exception as e:
            logger.warning("[ThreadManager] Load failed: %s", e)
            self._threads = []

    def _save(self):
        try:
            data = {"threads": [t.to_dict() for t in self._threads]}
            _REGISTRY_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning("[ThreadManager] Save failed: %s", e)

    def get_or_create_thread(self, platform: str, topic: str,
                              project: Optional[str] = None) -> ConversationThread:
        """Find existing thread or create a new one."""
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.THREAD_MAX_AGE_DAYS)).isoformat()

        for t in self._threads:
            if (t.platform == platform
                    and t.topic.lower() == topic.lower()
                    and (project is None or t.project == project)
                    and t.last_used >= cutoff):
                t.last_used = datetime.now(timezone.utc).isoformat()
                self._save()
                return t

        new_thread = ConversationThread(
            thread_id=str(uuid.uuid4()),
            platform=platform,
            topic=topic,
            project=project,
        )
        self._threads.append(new_thread)
        self._save()
        return new_thread

    def save_thread(self, thread: ConversationThread):
        for i, t in enumerate(self._threads):
            if t.thread_id == thread.thread_id:
                self._threads[i] = thread
                self._save()
                return
        self._threads.append(thread)
        self._save()

    def get_threads_for_project(self, project: str) -> List[ConversationThread]:
        return [t for t in self._threads if t.project == project]

    def get_all(self) -> List[ConversationThread]:
        return list(self._threads)


# Singleton
_thread_manager: Optional[ThreadManager] = None


def get_thread_manager() -> ThreadManager:
    global _thread_manager
    if _thread_manager is None:
        _thread_manager = ThreadManager()
    return _thread_manager
