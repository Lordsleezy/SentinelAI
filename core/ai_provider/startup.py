"""AI provider startup, status, and chat fallback chain."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("sentinel.ai_provider")

_ROOT = Path(__file__).resolve().parents[2]
_LOG_PATH = _ROOT / "data" / "logs" / "provider_startup.log"
_OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
_BOOTSTRAP_STARTED = False


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_provider(step: str, *, success: bool = True, detail: Optional[Dict[str, Any]] = None, error: str = "") -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": _utc(),
        "step": step,
        "success": success,
        "detail": detail or {},
        "error": error[:500] if error else "",
    }
    with _LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    if success:
        logger.info("provider %s %s", step, detail or "")
    else:
        logger.warning("provider %s failed: %s", step, error or detail)


def _download_progress() -> int:
    try:
        from core.onboarding.pipeline import get_onboarding_pipeline
        return int(get_onboarding_pipeline().progress().get("percent") or 0)
    except Exception:
        return 0


def _model_loaded(tag: str) -> bool:
    try:
        import httpx
        r = httpx.get(f"{_OLLAMA_HOST}/api/ps", timeout=2)
        if r.status_code != 200:
            return False
        for m in r.json().get("models", []):
            name = (m.get("name") or "").lower()
            if tag.lower() in name or name.startswith(tag.split(":")[0].lower()):
                return True
    except Exception:
        pass
    return False


def get_ai_status() -> Dict[str, Any]:
    from core.model_runtime import get_model_runtime

    rt = get_model_runtime()
    quick = rt.readiness_quick()
    req = quick.get("required") or rt.required_models(quick=True)
    primary = req.get("dolphin") or req.get("llama") or "llama3.2:3b"
    ollama_running = rt.ollama_running()
    ollama_installed = rt.ollama_installed()
    models = quick.get("models") or []
    model_installed = all(m.get("installed") for m in models if m.get("required")) if models else False
    model_loaded = _model_loaded(primary) if ollama_running else False

    web_search_ready = bool(
        os.getenv("BRAVE_API_KEY")
        or os.getenv("SERPAPI_API_KEY")
        or os.getenv("TAVILY_API_KEY")
    )
    memory_ready = False
    try:
        from pathlib import Path as P
        memory_ready = (P(_ROOT) / "memory" / "hot_memory.db").is_file() or (P(_ROOT) / "data" / "sentinelai.db").is_file()
    except Exception:
        memory_ready = True

    provider_ready = ollama_running and (model_installed or model_loaded)
    if not provider_ready:
        provider_ready = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY"))

    pull = rt._state.get("pull") or {}
    download_progress = int(pull.get("percent") or _download_progress())

    return {
        "ollama_installed": ollama_installed,
        "ollama_running": ollama_running,
        "model_installed": model_installed,
        "model_loaded": model_loaded,
        "primary_model": primary,
        "provider_ready": provider_ready,
        "download_progress": download_progress,
        "download_message": pull.get("message", ""),
        "web_search_ready": web_search_ready,
        "memory_ready": memory_ready,
        "cloud_fallbacks": {
            "claude": bool(os.getenv("ANTHROPIC_API_KEY")),
            "openai": bool(os.getenv("OPENAI_API_KEY")),
        },
        "degraded": not (ollama_running and model_loaded),
        "allow_chat": True,
    }


def _model_tag_installed(tag: str, installed: Dict[str, str]) -> bool:
    if not installed:
        return False
    base = tag.split(":")[0].lower()
    for name in installed:
        n = name.lower()
        if n == tag.lower() or n.startswith(base + ":") or n.startswith(base):
            return True
    return False


def _pick_ollama_model(rt: Any) -> str:
    req = rt.required_models(quick=True)
    preferred = req.get("dolphin") or req.get("llama") or os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    if not rt.ollama_running():
        return preferred
    installed = rt.list_installed_models()
    if _model_tag_installed(preferred, installed):
        return preferred
    if installed:
        return next(iter(installed.keys()))
    return preferred


def _try_ollama(message: str, system: str, model: str, timeout: float = 45.0) -> Optional[str]:
    try:
        import httpx
        with httpx.Client(timeout=timeout) as client:
            r = client.post(
                f"{_OLLAMA_HOST}/api/generate",
                json={
                    "model": model,
                    "prompt": message,
                    "system": system,
                    "stream": False,
                    "options": {"num_predict": 512},
                },
            )
        if r.status_code == 200:
            text = (r.json().get("response") or "").strip()
            return text or None
    except Exception as e:
        log_provider("ollama_generate", success=False, error=str(e))
    return None


def _try_claude(message: str) -> Optional[str]:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return None
    try:
        import httpx
        with httpx.Client(timeout=30.0) as client:
            r = client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 512,
                    "messages": [{"role": "user", "content": message}],
                },
            )
        if r.status_code == 200:
            parts = r.json().get("content", [])
            if parts:
                return (parts[0].get("text") or "").strip() or None
    except Exception as e:
        log_provider("claude_fallback", success=False, error=str(e))
    return None


def _try_openai(message: str) -> Optional[str]:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return None
    try:
        import httpx
        with httpx.Client(timeout=30.0) as client:
            r = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
                json={
                    "model": os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
                    "max_tokens": 512,
                    "messages": [{"role": "user", "content": message}],
                },
            )
        if r.status_code == 200:
            choices = r.json().get("choices", [])
            if choices:
                return (choices[0].get("message", {}).get("content") or "").strip() or None
    except Exception as e:
        log_provider("openai_fallback", success=False, error=str(e))
    return None


def _web_assistant_reply(message: str) -> str:
    return (
        "I'm here, though my full local model is still getting ready. "
        "You can keep chatting — I'll give my best answer. "
        "For richer replies, add a cloud API key in Settings under AI when you're ready."
    )


def chat_with_fallbacks(
    message: str,
    system: str = "",
    *,
    memory_context: str = "",
    tools_context: str = "",
) -> Dict[str, Any]:
    """Never return empty — always a usable chat payload."""
    from core.model_runtime import get_model_runtime

    try:
        from core.chat.context import build_system_prompt, prepare_chat_llm_input
        user_prompt, system = prepare_chat_llm_input(
            message, system or "You are Sentinel, a helpful personal AI assistant. Be concise and capable.",
            memory_context=memory_context,
            tools_context=tools_context,
        )
    except Exception:
        user_prompt = (message or "").strip()
        if not system:
            system = "You are Sentinel, a helpful local-first AI assistant. Be concise and capable."

    rt = get_model_runtime()
    model = _pick_ollama_model(rt)

    if rt.ollama_installed() and not rt.ollama_running():
        threading.Thread(target=lambda: rt.ensure_ollama_running(), daemon=True).start()

    if rt.ollama_running():
        installed = rt.list_installed_models()
        if _model_tag_installed(model, installed):
            loaded = _model_loaded(model)
            timeout = 45.0 if loaded else 18.0
            text = _try_ollama(user_prompt, system, model, timeout=timeout)
            if text:
                log_provider("chat_source", detail={"source": "ollama", "model": model})
                return {"text": text, "source": "ollama", "degraded": False, "model": model}
        else:
            log_provider("ollama_skip", detail={"model": model, "reason": "not_installed"})

    text = _try_claude(user_prompt)
    if text:
        log_provider("chat_source", detail={"source": "claude"})
        return {"text": text, "source": "claude", "degraded": True}

    text = _try_openai(user_prompt)
    if text:
        log_provider("chat_source", detail={"source": "openai"})
        return {"text": text, "source": "openai", "degraded": True}

    log_provider("chat_source", detail={"source": "web_assistant"})
    return {"text": _web_assistant_reply(user_prompt), "source": "web_assistant", "degraded": True}


def bootstrap_providers() -> None:
    """Non-blocking startup: Ollama + models in background; chat uses fallbacks until ready."""
    global _BOOTSTRAP_STARTED
    if _BOOTSTRAP_STARTED:
        return
    _BOOTSTRAP_STARTED = True
    log_provider("bootstrap_start")

    def _work() -> None:
        try:
            from core.model_runtime import get_model_runtime
            from core.onboarding.pipeline import get_onboarding_pipeline

            rt = get_model_runtime()
            if rt.ollama_installed() and not rt.ollama_running():
                log_provider("bootstrap_start_ollama")
                rt.ensure_ollama_running()

            pipe = get_onboarding_pipeline()
            if not rt.readiness_quick().get("all_required_models"):
                log_provider("bootstrap_pull_models")
                pipe.start_background_setup(pipe.run_fast_scan() if not rt.ollama_installed() else {})

            status = get_ai_status()
            log_provider("bootstrap_complete", detail=status)
        except Exception as e:
            log_provider("bootstrap_error", success=False, error=str(e))

    threading.Thread(target=_work, name="ai-provider-bootstrap", daemon=True).start()
