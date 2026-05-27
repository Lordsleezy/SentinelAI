"""Semantic retrieval facade over persistent memory."""

from typing import Any, Dict, List

from memory.persistent_memory import get_memory


class SemanticRetriever:
    def retrieve(self, query: str, namespaces: List[str], limit_per_namespace: int = 5) -> List[Dict[str, Any]]:
        memory = get_memory()
        results = []
        for namespace in namespaces:
            results.extend(memory.recall(namespace, query, limit_per_namespace))
        return sorted(results, key=lambda item: item["score"], reverse=True)
