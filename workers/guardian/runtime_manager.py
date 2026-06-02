"""
Guardian Brain Runtime Manager — Ollama models, GPU, memory, install guidance.

Facade over guardian_runtime_manager with professional UX fields.
"""
from __future__ import annotations

import re
import subprocess
from typing import Any, Dict, List, Optional

from workers.guardian.guardian_runtime_manager import (
    SUPPORTED_MODEL_HINTS,
    get_runtime_dashboard,
    get_selected_model,
    list_ollama_models,
    load_models_config,
    save_models_config,
    generate,
)

# Re-export for API compatibility
__all__ = [
    "get_brain_status",
    "get_runtime_dashboard",
    "list_ollama_models",
    "save_models_config",
    "get_selected_model",
    "generate",
    "suggest_install_models",
    "pull_model",
]


def _friendly_model_name(model: str) -> str:
    m = model.lower()
    if "dolphin" in m:
        if "mistral" in m:
            return "Dolphin Mistral"
        if "llama" in m:
            return "Dolphin Llama"
        return "Dolphin 3" if "3" in m or "8b" in m else "Dolphin"
    if "qwen" in m:
        return "Qwen 2.5" if "2.5" in m or "2" in m else "Qwen"
    if "deepseek" in m:
        return "DeepSeek"
    if "llama" in m:
        return "Llama 3" if "3" in m else "Llama"
    if "mistral" in m:
        return "Mistral"
    if "hermes" in m or "openhermes" in m:
        return "Nous Hermes / OpenHermes"
    return model.split(":")[0].replace("-", " ").title()


def _detect_gpu() -> Dict[str, Any]:
    info: Dict[str, Any] = {"detected": False, "label": "CPU inference"}
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=6,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            line = proc.stdout.strip().split("\n")[0]
            parts = [p.strip() for p in line.split(",")]
            name = parts[0] if parts else "NVIDIA GPU"
            info["detected"] = True
            info["name"] = name
            info["label"] = "RTX / NVIDIA GPU detected" if "rtx" in name.lower() or "geforce" in name.lower() else name
            if len(parts) >= 3:
                info["vram_total"] = parts[1]
                info["vram_used"] = parts[2]
    except Exception:
        pass
    return info


def suggest_install_models() -> List[Dict[str, str]]:
    """Recommended pulls for Guardian Brain."""
    return [
        {"id": "dolphin3:8b", "label": "Dolphin 3 8B", "command": "ollama pull dolphin3:8b"},
        {"id": "qwen2.5:7b", "label": "Qwen 2.5 7B", "command": "ollama pull qwen2.5:7b"},
        {"id": "deepseek-r1:8b", "label": "DeepSeek R1 8B", "command": "ollama pull deepseek-r1:8b"},
        {"id": "llama3.2:3b", "label": "Llama 3.2 3B", "command": "ollama pull llama3.2:3b"},
        {"id": "mistral:7b", "label": "Mistral 7B", "command": "ollama pull mistral:7b"},
    ]


def pull_model(model: str) -> Dict[str, Any]:
    import subprocess
    try:
        proc = subprocess.run(
            ["ollama", "pull", model],
            capture_output=True, text=True, timeout=600,
        )
        return {
            "ok": proc.returncode == 0,
            "stdout": (proc.stdout or "")[-2000:],
            "stderr": (proc.stderr or "")[-500:],
        }
    except FileNotFoundError:
        return {"ok": False, "error": "ollama not in PATH"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "pull timed out (10m)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_brain_status() -> Dict[str, Any]:
    """Professional runtime panel payload."""
    dash = get_runtime_dashboard()
    models = list_ollama_models(dash.get("ollama_url"))
    selected = get_selected_model()
    gpu = _detect_gpu()
    installed = len(models) > 0

    status_label = "Ready"
    if dash.get("status") == "loading":
        status_label = "Loading"
    elif dash.get("status") == "error":
        status_label = "Error"
    elif not installed:
        status_label = "No Guardian Brain installed"

    return {
        "guardian_brain": True,
        "current_model": selected,
        "current_model_friendly": _friendly_model_name(selected) if selected else None,
        "status": status_label,
        "status_raw": dash.get("status"),
        "gpu": gpu,
        "vram_mb": dash.get("vram_mb"),
        "inference_ms_last": dash.get("inference_ms_last"),
        "loaded_since": dash.get("loaded_since"),
        "last_task": dash.get("last_task"),
        "installed_models": models,
        "install_suggestions": suggest_install_models() if not installed else [],
        "no_models": not installed,
        "ollama_url": dash.get("ollama_url"),
        "logs": dash.get("logs", [])[-20:],
        "memory_note": f"VRAM in use: {dash.get('vram_mb')} MB" if dash.get("vram_mb") else "Memory: n/a",
    }
