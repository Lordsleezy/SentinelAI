"""
workers/setup/machine_scanner.py — Non-blocking hardware detection for first launch.
Uses core.onboarding.hardware_probe (no WMIC, no ollama CLI).
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from core.onboarding.debug_logger import StepWatchdog
from core.onboarding.hardware_probe import probe_machine_profile


class MachineScanner:
    """Scans hardware and software without blocking onboarding."""

    CACHE_PATH = os.path.expanduser("~/.sentinelai/machine_profile.json")

    def scan(self) -> dict:
        with StepWatchdog("machine_scanner.scan"):
            profile = probe_machine_profile()
            profile["scanned_at"] = datetime.now().isoformat()
            os.makedirs(os.path.dirname(self.CACHE_PATH), exist_ok=True)
            with open(self.CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(profile, f, indent=2)
            return profile

    def load_cached(self) -> dict | None:
        try:
            with open(self.CACHE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None


_scanner_instance = None


def get_machine_scanner() -> MachineScanner:
    global _scanner_instance
    if _scanner_instance is None:
        _scanner_instance = MachineScanner()
    return _scanner_instance
