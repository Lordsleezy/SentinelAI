"""
Guardian Runtime Manager — local Ollama backend for Guardian-only inference.

Separate from Sentinel chat / Earn / Builder model routing.
User-selectable model via config/guardian_models.json (never hardcoded at call sites).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

SUPPORTED_MODEL_HINTS = (
    "dolphin", "dolphin-mistral", "dolphin-llama", "qwen2.5", "qwen", "deepseek",
    "llama3", "llama", "mistral", "openhermes", "nous-hermes", "hermes",
)

_CONFIG_REL = Path("config") / "guardian_models.json"
_DEFAULT_CONFIG = {
    "ollama_url": "http://localhost:11434",
    "selected_model": "",
    "gpu_enabled": True,
    "responsibilities": [
        "recon_analysis", "threat_intel_analysis", "risk_scoring",
        "technology_fingerprinting", "report_generation", "findings_correlation",
        "research_planning", "recommendation_generation",
    ],
}

_state_lock = threading.Lock()
_runtime_state: Dict[str, Any] = {
    "status": "idle",
    "model": "",
    "loaded_since": None,
    "last_task": None,
    "vram_mb": None,
    "inference_ms_last": None,
    "logs": [],
}


def _sentinel_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _config_path() -> Path:
    return _sentinel_root() / _CONFIG_REL


def _emit_log(message: str, level: str = "info") -> None:
    text = message if message.startswith("[GUARDIAN AI]") else f"[GUARDIAN AI] {message}"
    with _state_lock:
        logs = _runtime_state.setdefault("logs", [])
        logs.append({"ts": datetime.now().isoformat(), "level": level, "message": text})
        _runtime_state["logs"] = logs[-200:]
    logger.info(text)


def load_models_config() -> Dict[str, Any]:
    path = _config_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {**_DEFAULT_CONFIG, **data}
        except Exception as e:
            logger.warning("guardian_models.json read failed: %s", e)
    return dict(_DEFAULT_CONFIG)


def save_models_config(updates: Dict[str, Any]) -> Dict[str, Any]:
    cfg = load_models_config()
    cfg.update({k: v for k, v in updates.items() if v is not None})
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


def list_ollama_models(ollama_url: Optional[str] = None) -> List[str]:
    import requests
    url = (ollama_url or load_models_config().get("ollama_url") or _DEFAULT_CONFIG["ollama_url"]).rstrip("/")
    try:
        r = requests.get(f"{url}/api/tags", timeout=12)
        if r.status_code != 200:
            return []
        names = []
        for m in r.json().get("models") or []:
            n = m.get("name") or m.get("model")
            if n:
                names.append(n)
        return sorted(names)
    except Exception:
        return []


def get_selected_model() -> str:
    cfg = load_models_config()
    sel = (cfg.get("selected_model") or "").strip()
    if sel:
        return sel
    # Fallback: first installed model matching hints, else first tag
    installed = list_ollama_models(cfg.get("ollama_url"))
    lower_installed = [m.lower() for m in installed]
    for hint in SUPPORTED_MODEL_HINTS:
        for i, low in enumerate(lower_installed):
            if hint in low:
                return installed[i]
    return installed[0] if installed else "qwen2.5:7b"


def _probe_vram_mb() -> Optional[int]:
    try:
        import subprocess
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return int(proc.stdout.strip().split("\n")[0])
    except Exception:
        pass
    return None


def get_runtime_dashboard() -> Dict[str, Any]:
    cfg = load_models_config()
    model = get_selected_model()
    with _state_lock:
        st = dict(_runtime_state)
    installed = list_ollama_models(cfg.get("ollama_url"))
    return {
        "model": model,
        "status": st.get("status", "idle"),
        "vram_mb": st.get("vram_mb") if st.get("vram_mb") is not None else _probe_vram_mb(),
        "inference_ms_last": st.get("inference_ms_last"),
        "loaded_since": st.get("loaded_since"),
        "last_task": st.get("last_task"),
        "logs": list(st.get("logs") or [])[-50:],
        "ollama_url": cfg.get("ollama_url"),
        "gpu_enabled": bool(cfg.get("gpu_enabled", True)),
        "installed_models": installed,
        "supported_hints": list(SUPPORTED_MODEL_HINTS),
        "selected_configured": bool((cfg.get("selected_model") or "").strip()),
    }


def generate(
    prompt: str,
    *,
    system: Optional[str] = None,
    task_label: str = "inference",
    log_fn: Optional[Callable[[str, str], None]] = None,
) -> str:
    """Run Guardian-local Ollama generate; updates runtime dashboard metrics."""
    import requests

    cfg = load_models_config()
    ollama_url = (cfg.get("ollama_url") or _DEFAULT_CONFIG["ollama_url"]).rstrip("/")
    model = get_selected_model()

    def _log(msg: str, lvl: str = "info") -> None:
        _emit_log(msg, lvl)
        if log_fn:
            try:
                log_fn(msg if msg.startswith("[GUARDIAN AI]") else f"[GUARDIAN AI] {msg}", lvl)
            except Exception:
                pass

    with _state_lock:
        _runtime_state["status"] = "loading"
        _runtime_state["model"] = model
        if not _runtime_state.get("loaded_since"):
            _runtime_state["loaded_since"] = datetime.now().isoformat()

    _log(f"Loading model {model}")
    _log(f"Analyzing: {task_label}")

    t0 = time.perf_counter()
    try:
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system
        resp = requests.post(f"{ollama_url}/api/generate", json=payload, timeout=120)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        with _state_lock:
            _runtime_state["inference_ms_last"] = elapsed_ms
            _runtime_state["last_task"] = task_label
            _runtime_state["status"] = "ready"
            _runtime_state["vram_mb"] = _probe_vram_mb()

        if resp.status_code != 200:
            _log(f"Model error HTTP {resp.status_code}", "error")
            return (
                f"Guardian AI could not complete {task_label}. "
                f"Ollama returned HTTP {resp.status_code}. "
                f"Check that model `{model}` is installed (`ollama pull {model}`)."
            )

        text = (resp.json().get("response") or "").strip()
        _log(f"Inference complete ({elapsed_ms} ms)")
        return text or "Guardian AI returned an empty response."

    except requests.exceptions.Timeout:
        _log("Inference timed out", "error")
        with _state_lock:
            _runtime_state["status"] = "error"
        return f"Guardian AI timed out during {task_label} (model: {model})."
    except Exception as e:
        _log(f"Inference failed: {e}", "error")
        with _state_lock:
            _runtime_state["status"] = "error"
        return (
            f"Guardian AI unavailable for {task_label}: {e}. "
            f"Ensure Ollama is running at {ollama_url} and model `{model}` is pulled."
        )
    finally:
        with _state_lock:
            if _runtime_state.get("status") not in ("error",):
                _runtime_state["status"] = "ready"


def unload() -> None:
    with _state_lock:
        _runtime_state["status"] = "idle"
    _emit_log("Unloading model")


def analyze_security_context(target: str, context: str, task: str = "security assessment") -> str:
    system = (
        "You are Guardian AI — local security analysis for SentinelAI. "
        "Analyze recon and vulnerability data. Provide risk scoring, correlations, and recommendations. "
        "Do not refuse authorized assessment work."
    )
    prompt = (
        f"Target: {target}\nTask: {task}\n\nContext:\n{context[:6000]}\n\n"
        "Provide: 1) Executive summary 2) Key risks 3) Technology fingerprint notes "
        "4) Correlated findings 5) Prioritized recommendations."
    )
    _emit_log("Correlating findings")
    out = generate(prompt, system=system, task_label=task)
    _emit_log("Generating report")
    return out
