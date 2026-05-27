"""Task capability registry for local and frontier models."""

import os
from typing import Dict, List


class CapabilityRegistry:
    def __init__(self):
        self.models: Dict[str, Dict] = {
            "ollama_small": {
                "provider": "ollama",
                "model": os.getenv("OLLAMA_SMALL_MODEL", "llama3.2:1b"),
                "capabilities": ["summarize", "classify", "simple_research"],
                "reasoning_tier": "low",
                "local": True,
            },
            "ollama_coder": {
                "provider": "ollama",
                "model": os.getenv("OLLAMA_MODEL", "qwen2.5-coder:14b"),
                "capabilities": ["coding", "debugging", "repo_analysis"],
                "reasoning_tier": "medium",
                "local": True,
            },
            "frontier_high_reasoning": {
                "provider": os.getenv("FRONTIER_PROVIDER", "disabled"),
                "model": os.getenv("FRONTIER_MODEL", ""),
                "capabilities": ["high_reasoning", "architecture", "complex_debugging"],
                "reasoning_tier": "high",
                "local": False,
            },
        }

    def list_models(self) -> Dict[str, Dict]:
        return self.models

    def candidates_for(self, capability: str) -> List[Dict]:
        return [
            {"id": model_id, **model}
            for model_id, model in self.models.items()
            if capability in model["capabilities"]
        ]
