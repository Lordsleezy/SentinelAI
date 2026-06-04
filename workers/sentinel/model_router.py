"""
Sentinel Model Router — single source of LLM selection.

Replaces three earlier files (model_router/router.py, the original
workers/sentinel/model_router.py, and workers/orchestration/model_selector.py)
with one router that supports all three legacy surfaces:

    router.route(role, task_type, complexity)
        — pick a model by role for a known internal engine.

    router.route_for_task(task_type, prompt, prefer_local)
        — legacy task/prompt-based selection used by /api/model-router/route
        and the orchestration execution context.

    router.select(task, task_type, complexity)
        — legacy ModelSelector surface used by workers/orchestration/pipeline.

    router.status()
        — model catalog snapshot used by /api/model-router/status.

    get_runtime_status()
        — runtime panel snapshot used by /api/model/runtime/status.

Selection rules (in order):
    1. Use the role config if present.
    2. Prefer locally-available Ollama models.
    3. Escalate to Claude Haiku, then Claude Sonnet if ANTHROPIC_API_KEY is set.
    4. Fall back to the configured preferred model name (whether available or not).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sentinel.model_router")

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "model_config.json"

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


# ── Role config: which model handles which Sentinel role ───────────────────
_DEFAULT_ROLES: Dict[str, Dict[str, str]] = {
    "general_chat": {"preferred": "qwen2.5-coder:7b", "fallback": "claude-haiku-4-5-20251001"},
    "builder":      {"preferred": "qwen2.5-coder:14b", "fallback": "claude-sonnet-4-5"},
    "guardian":     {"preferred": "qwen2.5-coder:14b", "fallback": "claude-sonnet-4-5"},
    "research":     {"preferred": "qwen2.5-coder:14b", "fallback": "claude-sonnet-4-5"},
    "vision":       {"preferred": "llava:13b",         "fallback": "qwen2.5-coder:7b"},
    "decomposer":   {"preferred": "qwen2.5-coder:14b", "fallback": "qwen2.5-coder:7b"},
}

# ── Tier table: legacy ModelSelector compatibility ─────────────────────────
_TIERS: Dict[str, Dict[str, Any]] = {
    "fast_local":   {"provider": "ollama", "model": "qwen2.5-coder:7b",       "capabilities": ["GENERAL", "WEB", "MEMORY"]},
    "strong_local": {"provider": "ollama", "model": "qwen2.5-coder:14b",      "capabilities": ["CODE", "FILE", "CALENDAR", "MUSIC"]},
    "vision_local": {"provider": "ollama", "model": "llava:13b",              "capabilities": ["CAMERA", "IMAGE"]},
    "fast_cloud":   {"provider": "claude", "model": "claude-haiku-4-5-20251001", "capabilities": ["CODE", "FILE", "WEB", "GENERAL"]},
    "strong_cloud": {"provider": "claude", "model": "claude-sonnet-4-5",      "capabilities": ["CODE", "FILE", "WEB", "GENERAL", "HOME", "FINANCE"]},
}

# ── Engine → role mapping ──────────────────────────────────────────────────
_ENGINE_ROLE_MAP = {
    "general":       "general_chat",
    "forge":         "builder",
    "builder":       "builder",
    "guardian":      "guardian",
    "earn":          "research",
    "earn_research": "research",
    "learning":      "research",
    "vision":        "vision",
    "decomposer":    "decomposer",
}

# ── Legacy task_type → capability mapping (replaces DefaultRoutingPolicy) ──
def _task_type_to_capability(task_type: str, prompt: str) -> str:
    text = f"{task_type} {prompt}".lower()
    if any(w in text for w in ("architecture", "deep reasoning", "complex", "critical")):
        return "high_reasoning"
    if any(w in text for w in ("code", "debug", "repo", "test", "patch")):
        return "coding"
    if any(w in text for w in ("summarize", "classify", "brief")):
        return "summarize"
    return "simple_research"


# Capability → ordered list of tier ids that satisfy it. Earlier entries win
# when prefer_local is True.
_CAPABILITY_TIERS = {
    "coding":           ["strong_local", "fast_local", "strong_cloud"],
    "high_reasoning":   ["strong_cloud", "strong_local"],
    "summarize":        ["fast_local", "strong_local", "fast_cloud"],
    "simple_research":  ["fast_local", "strong_local", "fast_cloud"],
}


def _load_config() -> Dict[str, Any]:
    if _CONFIG_PATH.is_file():
        try:
            return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.debug("model_config load failed: %s", e)
    return {"roles": _DEFAULT_ROLES}


class ModelRouter:
    """Unified model router (roles, tasks, tiers)."""

    def __init__(self) -> None:
        self._config = _load_config()
        self._ollama_host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
        self._anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        self._available_cache: Optional[List[str]] = None

    # ── Discovery ──────────────────────────────────────────────────────────
    def _get_available_ollama_models(self) -> List[str]:
        if not _HTTPX_AVAILABLE:
            return []
        try:
            with httpx.Client(timeout=5.0) as client:
                r = client.get(f"{self._ollama_host}/api/tags")
                if r.status_code == 200:
                    models = [m.get("name", "") for m in r.json().get("models", [])]
                    self._available_cache = models
                    return models
        except Exception as e:
            logger.debug("Ollama unreachable: %s", e)
        return []

    def _available_ollama(self) -> List[str]:
        if self._available_cache is None:
            self._get_available_ollama_models()
        return self._available_cache or []

    def _model_available(self, name: str) -> bool:
        available = self._available_ollama()
        if not available:
            # Treat as available when we can't probe — caller will see the
            # real error when the model is invoked.
            return True
        base = name.split(":")[0]
        return any(m == name or m.startswith(base) for m in available)

    # ── Primary surface: role-based ───────────────────────────────────────
    def route(self, role: str, task_type: str = "GENERAL", complexity: str = "medium") -> Dict[str, Any]:
        roles = self._config.get("roles") or _DEFAULT_ROLES
        spec = roles.get(role) or roles.get("general_chat") or _DEFAULT_ROLES["general_chat"]
        preferred = spec.get("preferred", "qwen2.5-coder:14b")
        fallback = spec.get("fallback", "claude-haiku-4-5-20251001")

        # Try preferred local first
        if self._model_available(preferred):
            return {
                "role": role,
                "provider": "ollama",
                "model": preferred,
                "preferred": preferred,
                "fallback": fallback,
                "source": "role_config",
            }

        # Escalate to fallback (Claude) when available
        if fallback.startswith("claude") and self._anthropic_key:
            return {
                "role": role,
                "provider": "claude",
                "model": fallback,
                "preferred": preferred,
                "fallback": fallback,
                "source": "fallback_cloud",
            }

        # Last resort — any installed local model
        available = self._available_ollama()
        return {
            "role": role,
            "provider": "ollama",
            "model": available[0] if available else preferred,
            "preferred": preferred,
            "fallback": fallback,
            "source": "any_local",
        }

    # ── Legacy task/prompt surface ────────────────────────────────────────
    def route_for_task(self, task_type: str, prompt: str = "", prefer_local: bool = True) -> Dict[str, Any]:
        capability = _task_type_to_capability(task_type, prompt)
        tier_order = _CAPABILITY_TIERS.get(capability, _CAPABILITY_TIERS["simple_research"])

        if not prefer_local:
            # Reverse so cloud-first
            tier_order = [t for t in tier_order if t.endswith("_cloud")] + \
                         [t for t in tier_order if not t.endswith("_cloud")]

        for tier_id in tier_order:
            tier = _TIERS[tier_id]
            if tier["provider"] == "ollama" and self._model_available(tier["model"]):
                return {"id": tier_id, **tier, "capability": capability}
            if tier["provider"] == "claude" and self._anthropic_key:
                return {"id": tier_id, **tier, "capability": capability}

        # Nothing matched — return the strongest local model name (even if unverified)
        return {"id": "strong_local", **_TIERS["strong_local"], "capability": capability}

    # ── Legacy ModelSelector surface ──────────────────────────────────────
    def select(self, task: str, task_type: str = "GENERAL", complexity: str = "medium") -> Dict[str, Any]:
        result = self.route_for_task(task_type, task, prefer_local=True)
        # Original ModelSelector also returned tier/rationale
        return {
            "provider": result.get("provider"),
            "model": result.get("model"),
            "tier": result.get("id"),
            "rationale": f"{complexity} {task_type} → {result.get('id')}",
            "capabilities": result.get("capabilities", []),
        }

    # ── Snapshots ──────────────────────────────────────────────────────────
    def status(self) -> Dict[str, Any]:
        return {
            "models": _TIERS,
            "available_local": self._available_ollama(),
            "claude_configured": bool(self._anthropic_key),
            "ollama_host": self._ollama_host,
        }


# ── Module-level helpers ───────────────────────────────────────────────────
_router: Optional[ModelRouter] = None


def get_model_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router


# Backwards-compat alias for the legacy ModelSelector callers.
def get_model_selector() -> ModelRouter:
    return get_model_router()


def route_for_engine(internal_engine: str) -> Dict[str, Any]:
    role = _ENGINE_ROLE_MAP.get(internal_engine, "general_chat")
    return get_model_router().route(role)


def get_runtime_status() -> Dict[str, Any]:
    """Runtime panel snapshot: loaded model, fallback state, Ollama reachability."""
    router = get_model_router()
    general = router.route("general_chat")
    guardian = router.route("guardian")
    builder = router.route("builder")
    available = router._available_ollama()
    ollama_up = False
    if _HTTPX_AVAILABLE:
        try:
            r = httpx.get(f"{router._ollama_host}/api/tags", timeout=3.0)
            ollama_up = r.status_code == 200
        except Exception:
            pass
    return {
        "ollama_running": ollama_up,
        "ollama_host": router._ollama_host,
        "available_models": available,
        "loaded_roles": {
            "general_chat": general,
            "guardian": guardian,
            "builder": builder,
        },
        # NOTE: VRAM telemetry is addressed separately under audit finding M2.
        "vram_usage": None,
        "vram_note": "VRAM telemetry not yet wired — Ollama manages model load",
        "fallback_active": general.get("source", "").startswith("fallback"),
        "runtime_status": "ready" if ollama_up else "ollama_offline",
    }
