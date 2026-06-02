"""
workers/setup/machine_scanner.py — Hardware detection and model recommendation.
Runs once on first launch. Results cached to ~/.sentinelai/machine_profile.json.
"""
import subprocess
import platform
import os
import json
from datetime import datetime


class MachineScanner:
    """Scans hardware and software to determine what's needed for Sentinel."""

    CACHE_PATH = os.path.expanduser("~/.sentinelai/machine_profile.json")

    def scan(self) -> dict:
        """Full machine scan. Returns profile dict."""
        profile = {
            'os': platform.system(),
            'os_version': platform.version(),
            'architecture': platform.machine(),
            'vram_gb': self._get_vram_gb(),
            'ram_gb': self._get_ram_gb(),
            'gpu_name': self._get_gpu_name(),
            'ollama_installed': self._check_ollama(),
            'ollama_running': self._check_ollama_running(),
            'recommended_model': None,
            'scanned_at': datetime.now().isoformat(),
        }
        profile['recommended_model'] = self._recommend_model(profile['vram_gb'])

        os.makedirs(os.path.dirname(self.CACHE_PATH), exist_ok=True)
        with open(self.CACHE_PATH, 'w') as f:
            json.dump(profile, f, indent=2)

        return profile

    def load_cached(self) -> dict | None:
        """Load cached profile if it exists."""
        try:
            with open(self.CACHE_PATH) as f:
                return json.load(f)
        except Exception:
            return None

    def _get_vram_gb(self) -> float:
        """Detect GPU VRAM using nvidia-smi or wmic."""
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=memory.total', '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                vram_mb = int(result.stdout.strip().split('\n')[0])
                return round(vram_mb / 1024, 1)
        except Exception:
            pass

        try:
            result = subprocess.run(
                ['wmic', 'path', 'win32_VideoController', 'get', 'AdapterRAM'],
                capture_output=True, text=True, timeout=5,
            )
            lines = [l.strip() for l in result.stdout.split('\n')
                     if l.strip() and l.strip().isdigit()]
            if lines:
                return round(int(lines[0]) / (1024 ** 3), 1)
        except Exception:
            pass

        return 0.0

    def _get_gpu_name(self) -> str:
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip().split('\n')[0]
        except Exception:
            pass
        try:
            result = subprocess.run(
                ['wmic', 'path', 'win32_VideoController', 'get', 'name'],
                capture_output=True, text=True, timeout=5,
            )
            lines = [l.strip() for l in result.stdout.split('\n')
                     if l.strip() and l.strip() != 'Name']
            if lines:
                return lines[0]
        except Exception:
            pass
        return 'Unknown GPU'

    def _get_ram_gb(self) -> float:
        try:
            import psutil
            return round(psutil.virtual_memory().total / (1024 ** 3), 1)
        except Exception:
            return 0.0

    def _check_ollama(self) -> bool:
        try:
            result = subprocess.run(
                ['ollama', '--version'],
                capture_output=True, timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _check_ollama_running(self) -> bool:
        try:
            import requests
            r = requests.get('http://localhost:11434/api/tags', timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    def _recommend_model(self, vram_gb: float) -> str:
        """Pick the best model for available VRAM."""
        if vram_gb >= 24:
            return 'qwen3:14b'
        elif vram_gb >= 14:
            return 'qwen2.5-coder:14b'
        elif vram_gb >= 8:
            return 'qwen2.5-coder:7b'
        elif vram_gb >= 5:
            return 'qwen2.5-coder:3b'
        else:
            return 'qwen2.5:1.5b'


_scanner_instance = None


def get_machine_scanner() -> MachineScanner:
    global _scanner_instance
    if _scanner_instance is None:
        _scanner_instance = MachineScanner()
    return _scanner_instance
