"""Model manager — recommend and install only Llama + Dolphin for hardware profile."""
from __future__ import annotations

import json
import logging
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sentinel.models")

_ROOT = Path(__file__).resolve().parents[2]
_STATE_PATH = _ROOT / "data" / "models" / "model_state.json"

# name -> (size_gb_approx, vram_gb_min)
CATALOG = {
    "llama3.2:3b": {"role": "llama", "size_gb": 2.0, "vram_gb": 4},
    "llama3.1:8b": {"role": "llama", "size_gb": 4.7, "vram_gb": 8},
    "llama3.1:70b": {"role": "llama", "size_gb": 40, "vram_gb": 48},
    "dolphin3:8b": {"role": "dolphin", "size_gb": 4.7, "vram_gb": 8},
    "dolphin-mistral:7b": {"role": "dolphin", "size_gb": 4.1, "vram_gb": 6},
    "mistral:7b": {"role": "general", "size_gb": 4.1, "vram_gb": 6},
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class ModelManager:
    def __init__(self) -> None:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load_state()
        self._pull_lock = threading.Lock()

    def _load_state(self) -> Dict[str, Any]:
        if _STATE_PATH.is_file():
            try:
                return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"installed": {}, "recommended": {}, "last_pull": {}}

    def _save_state(self) -> None:
        _STATE_PATH.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    def _hardware(self) -> Dict[str, float]:
        from core.dependency_manager.engine import _system_profile
        p = _system_profile()
        return {
            "ram_gb": float(p.get("ram_gb") or 8),
            "vram_gb": float(p.get("vram_gb") or 0),
            "disk_free_gb": float(p.get("disk_free_gb") or 10),
        }

    def recommend(self) -> Dict[str, Any]:
        hw = self._hardware()
        ram, vram, disk = hw["ram_gb"], hw["vram_gb"], hw["disk_free_gb"]
        llama = "llama3.2:3b"
        dolphin = None
        if ram >= 32 and (vram >= 8 or vram == 0) and disk >= 12:
            llama = "llama3.1:8b"
            dolphin = "dolphin3:8b"
        elif ram >= 16 and disk >= 10:
            llama = "llama3.1:8b" if vram >= 6 or vram == 0 else "llama3.2:3b"
            dolphin = "dolphin-mistral:7b" if vram >= 6 or (vram == 0 and ram >= 24) else None
        elif ram >= 12:
            llama = "llama3.2:3b"
            dolphin = "dolphin-mistral:7b" if vram >= 6 else None
        rec = {"llama": llama, "dolphin": dolphin, "hardware": hw, "reason": self._reason(llama, dolphin, hw)}
        self._state["recommended"] = rec
        self._save_state()
        return rec

    def _reason(self, llama: str, dolphin: Optional[str], hw: Dict[str, float]) -> str:
        return (
            f"RAM {hw['ram_gb']}GB, VRAM {hw['vram_gb']}GB, disk {hw['disk_free_gb']}GB free -> "
            f"Llama={llama}" + (f", Dolphin={dolphin}" if dolphin else " (Dolphin skipped - low VRAM/RAM)")
        )

    def list_models(self) -> List[Dict[str, Any]]:
        installed = self._ollama_list()
        out = []
        for name, meta in CATALOG.items():
            out.append({
                "name": name,
                "role": meta["role"],
                "size_gb": meta["size_gb"],
                "vram_gb": meta["vram_gb"],
                "installed": name in installed,
                "installed_version": installed.get(name, ""),
                "recommended": name in (
                    self._state.get("recommended", {}).get("llama"),
                    self._state.get("recommended", {}).get("dolphin"),
                ),
            })
        return out

    def _ollama_list(self) -> Dict[str, str]:
        try:
            r = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=30)
            found = {}
            for line in (r.stdout or "").splitlines()[1:]:
                parts = line.split()
                if parts:
                    found[parts[0]] = parts[1] if len(parts) > 1 else ""
            return found
        except Exception:
            return {}

    def install_recommended(self) -> Dict[str, Any]:
        rec = self.recommend()
        try:
            from core.model_runtime import get_model_runtime
            pull = get_model_runtime().install_required_models()
            return {"ok": pull.get("ok"), "recommended": rec, "results": pull.get("results", {})}
        except Exception:
            targets = [rec["llama"]]
            if rec.get("dolphin"):
                targets.append(rec["dolphin"])
            results = {}
            for model in targets:
                results[model] = self.pull_model(model)
            return {"ok": all(r.get("ok") for r in results.values()), "recommended": rec, "results": results}

    def pull_model(self, model_name: str) -> Dict[str, Any]:
        with self._pull_lock:
            try:
                from workers.guardian.runtime_manager import pull_model
                result = pull_model(model_name)
                if result.get("ok"):
                    self._state.setdefault("installed", {})[model_name] = _utc()
                    self._state.setdefault("last_pull", {})[model_name] = result
                    self._save_state()
                return result
            except Exception as e:
                return {"ok": False, "error": str(e)}

    def remove_model(self, model_name: str) -> Dict[str, Any]:
        try:
            r = subprocess.run(["ollama", "rm", model_name], capture_output=True, text=True, timeout=120)
            ok = r.returncode == 0
            if ok:
                self._state.get("installed", {}).pop(model_name, None)
                self._save_state()
            return {"ok": ok, "stderr": (r.stderr or "")[:300]}
        except Exception as e:
            return {"ok": False, "error": str(e)}


_mgr: Optional[ModelManager] = None


def get_model_manager() -> ModelManager:
    global _mgr
    if _mgr is None:
        _mgr = ModelManager()
    return _mgr
