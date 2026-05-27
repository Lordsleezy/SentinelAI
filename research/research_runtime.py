"""Live internet research runtime with persistent memory ingestion."""

from typing import Any, Dict, List, Optional

import db
from memory.persistent_memory import get_memory
from web_tools import FirecrawlClient, SerperClient, TavilyClient


class ResearchRuntime:
    """Provider-agnostic research orchestrator."""

    def __init__(self, providers: Optional[List[Any]] = None):
        self.providers = providers or [TavilyClient(), FirecrawlClient(), SerperClient()]

    def search(self, query: str, limit: int = 5, persist: bool = True) -> Dict[str, Any]:
        provider_results = []
        for provider in self.providers:
            try:
                result = provider.search(query, limit)
            except Exception as exc:
                result = {
                    "provider": provider.name,
                    "available": False,
                    "results": [],
                    "error": str(exc),
                }
            provider_results.append(result)

        flat_results = []
        for result in provider_results:
            for item in result.get("results", [])[:limit]:
                flat_results.append(
                    {
                        "provider": result["provider"],
                        "title": item.get("title") or item.get("name") or "",
                        "url": item.get("url") or item.get("link") or "",
                        "snippet": item.get("content") or item.get("snippet") or item.get("description") or "",
                    }
                )

        if persist and flat_results:
            memory = get_memory()
            for item in flat_results[: limit * 2]:
                memory.remember(
                    "research",
                    f"{item['title']}\n{item['snippet']}\n{item['url']}",
                    {"query": query, "provider": item["provider"], "url": item["url"]},
                )

        db.log_event("research_search", f"{query} ({len(flat_results)} results)")
        return {
            "query": query,
            "results": flat_results,
            "providers": provider_results,
            "available_provider_count": sum(1 for item in provider_results if item.get("available")),
        }


_runtime: Optional[ResearchRuntime] = None


def get_research_runtime() -> ResearchRuntime:
    global _runtime
    if _runtime is None:
        _runtime = ResearchRuntime()
    return _runtime
