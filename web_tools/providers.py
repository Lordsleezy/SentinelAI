"""
Optional web provider clients for live internet research.

No provider is required at startup. If API keys are absent, callers receive a
structured unavailable result rather than a crash.
"""

import os
from typing import Any, Dict, List

import httpx


class BaseWebProvider:
    name = "base"
    env_key = ""

    def available(self) -> bool:
        return bool(os.getenv(self.env_key))

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        raise NotImplementedError

    def unavailable(self) -> Dict[str, Any]:
        return {
            "provider": self.name,
            "available": False,
            "results": [],
            "error": f"{self.env_key} not configured",
        }


class TavilyClient(BaseWebProvider):
    name = "tavily"
    env_key = "TAVILY_API_KEY"

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        if not self.available():
            return self.unavailable()
        response = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": os.getenv(self.env_key),
                "query": query,
                "max_results": limit,
                "search_depth": "basic",
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        return {
            "provider": self.name,
            "available": True,
            "results": data.get("results", []),
            "error": "",
        }


class FirecrawlClient(BaseWebProvider):
    name = "firecrawl"
    env_key = "FIRECRAWL_API_KEY"

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        if not self.available():
            return self.unavailable()
        response = httpx.post(
            "https://api.firecrawl.dev/v1/search",
            headers={"Authorization": f"Bearer {os.getenv(self.env_key)}"},
            json={"query": query, "limit": limit},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        return {
            "provider": self.name,
            "available": True,
            "results": data.get("data", data.get("results", [])),
            "error": "",
        }


class SerperClient(BaseWebProvider):
    name = "serper"
    env_key = "SERPER_API_KEY"

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        if not self.available():
            return self.unavailable()
        response = httpx.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": os.getenv(self.env_key), "Content-Type": "application/json"},
            json={"q": query, "num": limit},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        organic: List[Dict[str, Any]] = data.get("organic", [])
        return {
            "provider": self.name,
            "available": True,
            "results": organic[:limit],
            "error": "",
        }
