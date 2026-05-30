from __future__ import annotations

import os
import re
import subprocess
from typing import Dict


def tier_for_vram(vram_gb: float) -> str:
    if vram_gb <= 0:
        return "minimal"
    if vram_gb < 6:
        return "minimal"
    if vram_gb < 8:
        return "basic"
    if vram_gb < 12:
        return "standard"
    if vram_gb < 16:
        return "full"
    return "unlimited"


def detect_hardware() -> Dict:
    gpu_name = "CPU only"
    gpu_vram_gb = 0.0
    cuda_available = False

    torch_info = _detect_with_torch()
    if torch_info:
        gpu_name = torch_info["gpu_name"]
        gpu_vram_gb = torch_info["gpu_vram_gb"]
        cuda_available = True
    else:
        smi_info = _detect_with_nvidia_smi()
        if smi_info:
            gpu_name = smi_info["gpu_name"]
            gpu_vram_gb = smi_info["gpu_vram_gb"]
            cuda_available = True

    ram_gb = _ram_gb()
    return {
        "gpu_name": str(gpu_name),
        "gpu_vram_gb": float(round(gpu_vram_gb, 2)),
        "ram_gb": float(round(ram_gb, 2)),
        "cpu_cores": int(os.cpu_count() or 1),
        "cuda_available": bool(cuda_available),
        "tier": tier_for_vram(float(gpu_vram_gb)),
    }


def _detect_with_torch():
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        index = torch.cuda.current_device()
        props = torch.cuda.get_device_properties(index)
        return {
            "gpu_name": props.name,
            "gpu_vram_gb": float(props.total_memory) / (1024 ** 3),
        }
    except Exception:
        return None


def _detect_with_nvidia_smi():
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    first = completed.stdout.strip().splitlines()[0]
    parts = [part.strip() for part in first.split(",")]
    if len(parts) < 2:
        return None
    match = re.search(r"[\d.]+", parts[1])
    if not match:
        return None
    return {
        "gpu_name": parts[0],
        "gpu_vram_gb": float(match.group(0)) / 1024.0,
    }


def _ram_gb() -> float:
    try:
        import psutil

        return float(psutil.virtual_memory().total) / (1024 ** 3)
    except Exception:
        return 0.0
