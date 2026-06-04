"""Non-blocking hardware / Ollama probes — never stall onboarding."""
from __future__ import annotations

import os
import platform
import shutil
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, Callable, Dict, Optional, TypeVar

from core.onboarding.debug_logger import StepWatchdog, log_event

T = TypeVar("T")

# WMIC is excluded: it frequently blocks 30s+ on Windows 10/11.
_NVIDIA_TIMEOUT = 3.0
_HTTP_TIMEOUT = 2.0
_RAM_TIMEOUT = 2.0
_PROBE_TOTAL_TIMEOUT = 8.0


def _run_timed(fn: Callable[[], T], timeout: float, step: str, default: T) -> T:
    with StepWatchdog(step, timeout_s=timeout):
        try:
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="probe") as pool:
                fut = pool.submit(fn)
                return fut.result(timeout=timeout)
        except FuturesTimeout:
            log_event(step, phase="timeout", success=False, error=f"exceeded {timeout}s", detail={"fallback": True})
            return default
        except Exception as e:
            log_event(step, phase="error", success=False, error=str(e), detail={"fallback": True})
            return default


def _probe_ram_gb() -> float:
    try:
        import psutil
        return round(psutil.virtual_memory().total / (1024 ** 3), 1)
    except Exception:
        return 8.0


def _probe_gpu_nvidia() -> Dict[str, Any]:
    if os.environ.get("SENTINEL_SIMULATE_NO_GPU") == "1":
        return {"gpu_name": "CPU inference (simulated)", "vram_gb": 0.0, "source": "simulated"}
    import subprocess
    out: Dict[str, Any] = {"gpu_name": "CPU inference", "vram_gb": 0.0, "source": "cpu_fallback"}
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=int(_NVIDIA_TIMEOUT),
        )
        if proc.returncode == 0 and proc.stdout.strip():
            line = proc.stdout.strip().splitlines()[0]
            parts = [p.strip() for p in line.split(",")]
            out["gpu_name"] = parts[0] if parts else "NVIDIA GPU"
            if len(parts) > 1:
                try:
                    out["vram_gb"] = round(float(parts[1]) / 1024, 1)
                except ValueError:
                    out["vram_gb"] = 0.0
            out["source"] = "nvidia-smi"
    except Exception:
        pass
    return out


def _probe_ollama_installed() -> bool:
    if os.environ.get("SENTINEL_SIMULATE_NO_OLLAMA") == "1":
        return False
    if shutil.which("ollama"):
        return True
    if platform.system() == "Windows":
        local = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama")
        for name in ("ollama.exe", "Ollama.exe"):
            if os.path.isfile(os.path.join(local, name)):
                return True
    return False


def _probe_ollama_running() -> bool:
    if os.environ.get("SENTINEL_SIMULATE_NO_OLLAMA") == "1" or os.environ.get("SENTINEL_SIMULATE_OFFLINE") == "1":
        return False
    try:
        import httpx
        r = httpx.get("http://127.0.0.1:11434/api/tags", timeout=_HTTP_TIMEOUT)
        return r.status_code == 200
    except Exception:
        return False


def recommend_models_fast(ram_gb: float, vram_gb: float, disk_free_gb: float = 10.0) -> Dict[str, Any]:
    """Pure logic — no imports that scan GPU again."""
    llama = "llama3.2:3b"
    dolphin = None
    if ram_gb >= 32 and (vram_gb >= 8 or vram_gb == 0) and disk_free_gb >= 12:
        llama = "llama3.1:8b"
        dolphin = "dolphin3:8b"
    elif ram_gb >= 16 and disk_free_gb >= 10:
        llama = "llama3.1:8b" if vram_gb >= 6 or vram_gb == 0 else "llama3.2:3b"
        dolphin = "dolphin-mistral:7b" if vram_gb >= 6 or (vram_gb == 0 and ram_gb >= 24) else None
    elif ram_gb >= 12:
        llama = "llama3.2:3b"
        dolphin = "dolphin-mistral:7b" if vram_gb >= 6 else None
    models = [{"name": llama, "role": "llama", "required": True}]
    if dolphin:
        models.append({"name": dolphin, "role": "dolphin", "required": True})
    return {
        "llama": llama,
        "dolphin": dolphin,
        "models": models,
        "hardware": {"ram_gb": ram_gb, "vram_gb": vram_gb, "disk_free_gb": disk_free_gb},
    }


def probe_machine_profile() -> Dict[str, Any]:
    """Full profile with per-probe timeouts and CPU fallbacks."""
    with StepWatchdog("probe_machine_profile"):
        ram_gb = _run_timed(_probe_ram_gb, _RAM_TIMEOUT, "probe_ram", 8.0)
        gpu = _run_timed(_probe_gpu_nvidia, _NVIDIA_TIMEOUT, "probe_gpu", {
            "gpu_name": "CPU inference",
            "vram_gb": 0.0,
            "source": "cpu_fallback",
        })
        ollama_installed = _run_timed(_probe_ollama_installed, 1.0, "probe_ollama_installed", False)
        ollama_running = _run_timed(_probe_ollama_running, _HTTP_TIMEOUT + 0.5, "probe_ollama_running", False)

        rec = recommend_models_fast(ram_gb, float(gpu.get("vram_gb") or 0))
        profile = {
            "os": platform.system(),
            "os_version": platform.version(),
            "architecture": platform.machine(),
            "ram_gb": ram_gb,
            "vram_gb": gpu.get("vram_gb", 0.0),
            "gpu_name": gpu.get("gpu_name", "CPU inference"),
            "gpu_probe_source": gpu.get("source", "unknown"),
            "ollama_installed": ollama_installed,
            "ollama_running": ollama_running,
            "recommended_model": rec.get("dolphin") or rec.get("llama"),
            "recommended": rec,
            "cpu_only_profile": gpu.get("source") == "cpu_fallback",
        }
        log_event("probe_machine_profile", phase="complete", success=True, detail=profile)
        return profile
