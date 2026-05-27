"""
Persistent memory facade for workflows, projects, codebases, and execution.
"""

from typing import Any, Dict, List, Optional

import db
from vector_store import SQLiteVectorStore


class PersistentMemory:
    """Long-term searchable memory for SentinelAI."""

    def __init__(self, store: Optional[SQLiteVectorStore] = None):
        self.store = store or SQLiteVectorStore()

    def initialize(self) -> None:
        self.store.initialize()
        db.log_event("memory_initialized", "Persistent vector memory initialized")

    def remember(
        self,
        namespace: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        memory_id = self.store.add(namespace, content, metadata)
        db.log_event("memory_recorded", f"{namespace}:{memory_id}")
        return memory_id

    def recall(self, namespace: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        return self.store.search(namespace, query, limit)

    def remember_workflow(self, workflow_id: int, content: str, metadata: Optional[Dict[str, Any]] = None) -> int:
        data = {"workflow_id": workflow_id}
        data.update(metadata or {})
        return self.remember("workflow", content, data)

    def remember_execution(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> int:
        return self.remember("execution", content, metadata)

    def remember_project(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> int:
        return self.remember("project", content, metadata)


_memory: Optional[PersistentMemory] = None


def get_memory() -> PersistentMemory:
    global _memory
    if _memory is None:
        _memory = PersistentMemory()
    return _memory


def initialize_memory() -> PersistentMemory:
    memory = get_memory()
    memory.initialize()
    return memory
