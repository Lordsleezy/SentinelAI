from __future__ import annotations

from typing import Dict, List, Optional

import requests

from models import model_registry


OLLAMA_URL = "http://127.0.0.1:11434"
BRAIN_TAG = "qwen3:8b"


class ModelUnavailableError(RuntimeError):
    pass


def get_model_for_task(task_type) -> str:
    model = model_registry.get_model_for_task(task_type) or model_registry.get_model_for_task("chat")
    if not model:
        return BRAIN_TAG
    if not model.get("downloaded"):
        brain = model_registry.get_model_for_task("chat")
        if brain and brain.get("downloaded"):
            return brain["ollama_tag"]
        return BRAIN_TAG
    return model["ollama_tag"]


def ensure_model_loaded(ollama_tag) -> bool:
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": ollama_tag, "prompt": "", "keep_alive": "10m", "stream": False},
            timeout=20,
        )
        if response.status_code == 200:
            model_registry.record_use(ollama_tag)
            return True
    except Exception:
        return False
    return False


def unload_model(ollama_tag) -> bool:
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": ollama_tag, "prompt": "", "keep_alive": 0, "stream": False},
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_loaded_models() -> List[str]:
    try:
        response = requests.get(f"{OLLAMA_URL}/api/ps", timeout=5)
        response.raise_for_status()
        data = response.json()
        return [model.get("name") or model.get("model") for model in data.get("models", []) if model.get("name") or model.get("model")]
    except Exception:
        return []


def smart_swap(needed_tag, hardware) -> bool:
    model_registry.init_registry()
    needed = _model_by_tag(needed_tag)
    if not needed:
        return False
    vram = float(hardware.get("gpu_vram_gb", 0) or 0)
    loaded = get_loaded_models()
    large_loaded = [tag for tag in loaded if (_model_by_tag(tag) or {}).get("min_vram_gb", 0) >= 6]
    tier = hardware.get("tier")

    if needed["min_vram_gb"] <= vram and (tier == "unlimited" or not large_loaded or needed_tag in loaded or needed["min_vram_gb"] < 6):
        return ensure_model_loaded(needed_tag)

    lru = _least_recently_used(large_loaded or loaded)
    if lru:
        unload_model(lru)
    return ensure_model_loaded(needed_tag)


def generate(ollama_tag, prompt, system=None, temperature=0, stream=False) -> str:
    payload: Dict = {
        "model": ollama_tag,
        "prompt": prompt,
        "stream": stream,
        "options": {"temperature": temperature},
    }
    if system:
        payload["system"] = system
    try:
        response = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        model_registry.record_use(ollama_tag)
        return data.get("response", "")
    except Exception as exc:
        raise ModelUnavailableError(f"Model unavailable: {ollama_tag}") from exc


def chat(ollama_tag, messages, temperature=0) -> str:
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={"model": ollama_tag, "messages": messages, "stream": False, "options": {"temperature": temperature}},
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        model_registry.record_use(ollama_tag)
        return (data.get("message") or {}).get("content", "")
    except Exception as exc:
        raise ModelUnavailableError(f"Model unavailable: {ollama_tag}") from exc


def _model_by_tag(tag: str) -> Optional[Dict]:
    for model in model_registry.get_all_models():
        if model["ollama_tag"] == tag:
            return model
    return None


def _least_recently_used(tags: List[str]) -> Optional[str]:
    models = [_model_by_tag(tag) for tag in tags]
    models = [model for model in models if model]
    if not models:
        return tags[0] if tags else None
    models.sort(key=lambda model: (model.get("last_used") or "", model.get("use_count") or 0))
    return models[0]["ollama_tag"]
