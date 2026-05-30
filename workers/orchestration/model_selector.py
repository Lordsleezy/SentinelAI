"""
Model Selector — Routes tasks to appropriate LLM based on type and complexity
"""
import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

CAPABILITY_DESCRIPTION = "Selects optimal model based on task type and complexity"

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


class ModelSelector:
    """Routes tasks to appropriate models"""

    # Model definitions by tier
    MODELS = {
        "fast_local": {
            "provider": "ollama",
            "model": "qwen2.5-coder:7b",
            "capabilities": ["GENERAL", "WEB", "MEMORY"],
            "latency_ms": 500,
            "quality": "medium"
        },
        "strong_local": {
            "provider": "ollama",
            "model": "qwen2.5-coder:14b",
            "capabilities": ["CODE", "FILE", "CALENDAR", "MUSIC"],
            "latency_ms": 2000,
            "quality": "high"
        },
        "vision_local": {
            "provider": "ollama",
            "model": "llava:13b",
            "capabilities": ["CAMERA", "IMAGE"],
            "latency_ms": 3000,
            "quality": "high"
        },
        "fast_cloud": {
            "provider": "claude",
            "model": "claude-haiku-4-5-20251001",
            "capabilities": ["CODE", "FILE", "WEB", "GENERAL"],
            "latency_ms": 1000,
            "quality": "high"
        },
        "strong_cloud": {
            "provider": "claude",
            "model": "claude-sonnet-4-5",
            "capabilities": ["CODE", "FILE", "WEB", "GENERAL", "HOME", "FINANCE"],
            "latency_ms": 2000,
            "quality": "very_high"
        }
    }

    def __init__(self):
        self.ollama_host = os.getenv('OLLAMA_HOST', 'http://127.0.0.1:11434')
        self.anthropic_key = os.getenv('ANTHROPIC_API_KEY')
        self._available_models_cache = None

    def _get_available_ollama_models(self) -> list:
        """Check which Ollama models are available"""
        if not HTTPX_AVAILABLE:
            return ["qwen2.5-coder:14b"]  # Default

        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{self.ollama_host}/api/tags")
                if response.status_code == 200:
                    data = response.json()
                    models = [m.get('name', '') for m in data.get('models', [])]
                    self._available_models_cache = models
                    logger.info(f"Available Ollama models: {models}")
                    return models
        except Exception as e:
            logger.warning(f"Could not fetch Ollama models: {e}")

        return ["qwen2.5-coder:14b"]  # Default fallback

    def select(
        self,
        task: str,
        task_type: str,
        complexity: str
    ) -> Dict[str, Any]:
        """Select optimal model for task"""

        # Quick selection logic
        if complexity == "SIMPLE":
            # Simple tasks use fast local model
            if self._is_model_available("qwen2.5-coder:7b"):
                return {
                    "provider": "ollama",
                    "model": "qwen2.5-coder:7b",
                    "tier": "fast_local",
                    "rationale": "Simple task - using fast local model"
                }

        # Complex tasks or high-quality needs
        if complexity == "COMPLEX" or task_type in ["CODE", "FILE"]:
            if self._is_model_available("qwen2.5-coder:14b"):
                return {
                    "provider": "ollama",
                    "model": "qwen2.5-coder:14b",
                    "tier": "strong_local",
                    "rationale": f"Complex {task_type} task - using strong local model"
                }

        # Vision tasks
        if task_type == "CAMERA":
            if self._is_model_available("llava:13b"):
                return {
                    "provider": "ollama",
                    "model": "llava:13b",
                    "tier": "vision_local",
                    "rationale": "Vision task - using llava"
                }

        # Fallback to cloud if available
        if self.anthropic_key:
            return {
                "provider": "claude",
                "model": "claude-haiku-4-5-20251001",
                "tier": "fast_cloud",
                "rationale": "Cloud fallback"
            }

        # Final fallback to strong local
        return {
            "provider": "ollama",
            "model": "qwen2.5-coder:14b",
            "tier": "strong_local",
            "rationale": "Default model selection"
        }

    def _is_model_available(self, model_name: str) -> bool:
        """Check if model is available"""
        if self._available_models_cache is None:
            self._get_available_ollama_models()

        if self._available_models_cache:
            return any(model_name in m for m in self._available_models_cache)

        # Assume available if we can't check
        return True

    def get_model_info(self, tier: str) -> Optional[Dict[str, Any]]:
        """Get info about a specific model tier"""
        return self.MODELS.get(tier)

    def list_available_tiers(self) -> Dict[str, Dict[str, Any]]:
        """List all available model tiers"""
        available = {}

        for tier, info in self.MODELS.items():
            if info["provider"] == "ollama":
                if self._is_model_available(info["model"]):
                    available[tier] = info
            elif info["provider"] == "claude":
                if self.anthropic_key:
                    available[tier] = info

        return available if available else {"strong_local": self.MODELS["strong_local"]}


_selector = None


def get_model_selector() -> ModelSelector:
    global _selector
    if _selector is None:
        _selector = ModelSelector()
    return _selector
