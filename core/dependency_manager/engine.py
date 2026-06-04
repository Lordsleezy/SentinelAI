"""Production dependency manager — detect, install, verify, resume."""
from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("sentinel.deps")

_ROOT = Path(__file__).resolve().parents[2]
_STATE_PATH = _ROOT / "data" / "dependencies" / "state.json"
_lock = threading.Lock()

COMPONENTS = (
    "python_runtime",
    "playwright",
    "chromium",
    "ollama",
    "guardian_tools",
    "vision_stack",
    "builder_godot",
    "update_service",
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _system_profile() -> Dict[str, Any]:
    profile: Dict[str, Any] = {
        "os": platform.system(),
        "os_release": platform.release(),
        "arch": platform.machine(),
        "cpu_count": os.cpu_count() or 1,
        "ram_gb": 0.0,
        "disk_free_gb": 0.0,
        "gpu": None,
        "vram_gb": 0.0,
    }
    try:
        import psutil
        profile["ram_gb"] = round(psutil.virtual_memory().total / 1e9, 2)
        du = psutil.disk_usage(str(_ROOT))
        profile["disk_free_gb"] = round(du.free / 1e9, 2)
    except Exception as e:
        profile["psutil_error"] = str(e)
    try:
        if shutil.which("nvidia-smi"):
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            line = (out.stdout or "").strip().splitlines()[0] if out.stdout else ""
            if line:
                parts = [p.strip() for p in line.split(",")]
                profile["gpu"] = parts[0] if parts else None
                if len(parts) > 1:
                    profile["vram_gb"] = round(float(parts[1]) / 1024, 2)
    except Exception:
        pass
    return profile


class DependencyManager:
    def __init__(self) -> None:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load_state()
        self._install_lock = threading.Lock()

    def _load_state(self) -> Dict[str, Any]:
        if _STATE_PATH.is_file():
            try:
                return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"components": {}, "last_scan": None, "profile": {}}

    def _save_state(self) -> None:
        _STATE_PATH.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    def scan_system(self) -> Dict[str, Any]:
        self._state["profile"] = _system_profile()
        self._state["last_scan"] = _utc()
        for cid in COMPONENTS:
            self._state["components"][cid] = self._probe_component(cid)
        self._save_state()
        return {"profile": self._state["profile"], "components": self.list_components()}

    def _probe_component(self, component_id: str) -> Dict[str, Any]:
        base = {
            "id": component_id,
            "version": "",
            "status": "missing",
            "download_percent": 0,
            "install_percent": 0,
            "verification": "pending",
            "message": "",
            "updated_at": _utc(),
        }
        try:
            if component_id == "python_runtime":
                base["version"] = platform.python_version()
                base["status"] = "installed"
                base["install_percent"] = 100
                base["verification"] = "ok"
            elif component_id == "playwright":
                import playwright  # noqa: F401
                base["status"] = "installed"
                base["version"] = "playwright"
                base["install_percent"] = 100
                base["verification"] = "ok"
            elif component_id == "chromium":
                r = subprocess.run(
                    [os.environ.get("PYTHON", "python"), "-m", "playwright", "install", "--dry-run", "chromium"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if "is already installed" in (r.stdout + r.stderr).lower() or r.returncode == 0:
                    base["status"] = "installed"
                    base["verification"] = "ok"
                    base["install_percent"] = 100
                else:
                    base["message"] = "Chromium not installed"
            elif component_id == "ollama":
                from core.model_runtime import get_model_runtime
                rt = get_model_runtime()
                if rt.ollama_installed():
                    if shutil.which("ollama"):
                        vr = subprocess.run(["ollama", "--version"], capture_output=True, text=True, timeout=10)
                        base["version"] = (vr.stdout or vr.stderr or "").strip()[:40]
                    base["status"] = "installed"
                    base["install_percent"] = 100
                    base["verification"] = "ok" if rt.ollama_running() else "partial"
                    if not rt.ollama_running():
                        base["message"] = "Ollama installed but not running"
                else:
                    base["message"] = "Ollama not installed"
            elif component_id == "guardian_tools":
                from core.capabilities.runtime_validator import validate_capability
                v = validate_capability("httpx")
                if v.installed:
                    base["status"] = "installed"
                    base["verification"] = "ok"
                    base["install_percent"] = 100
                else:
                    base["message"] = v.message or "Guardian tools incomplete"
            elif component_id == "vision_stack":
                pw = self._probe_component("playwright")
                ocr = False
                try:
                    import pytesseract  # noqa: F401
                    ocr = True
                except ImportError:
                    pass
                if pw["status"] == "installed":
                    base["status"] = "installed"
                    base["verification"] = "ok" if ocr else "partial"
                    base["install_percent"] = 100 if ocr else 80
                    base["message"] = "" if ocr else "Optional: pip install pytesseract pillow"
            elif component_id == "builder_godot":
                from core.capabilities.runtime_validator import validate_capability
                v = validate_capability("godot")
                base["status"] = "installed" if v.installed else "missing"
                base["verification"] = "ok" if v.installed else "pending"
                base["message"] = v.message or ""
            elif component_id == "update_service":
                base["status"] = "installed"
                base["verification"] = "ok"
                base["install_percent"] = 100
                base["version"] = "httpx"
        except Exception as e:
            base["message"] = str(e)[:200]
        return base

    def list_components(self) -> List[Dict[str, Any]]:
        comps = self._state.get("components") or {}
        return [comps.get(cid) or self._probe_component(cid) for cid in COMPONENTS]

    def install_component(
        self,
        component_id: str,
        *,
        progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        if component_id not in COMPONENTS:
            return {"ok": False, "error": f"unknown component: {component_id}"}

        def _progress(download: int, install: int, msg: str) -> None:
            comp = self._state["components"].setdefault(component_id, self._probe_component(component_id))
            comp["download_percent"] = download
            comp["install_percent"] = install
            comp["message"] = msg
            comp["status"] = "installing"
            self._save_state()
            if progress_cb:
                progress_cb(comp)

        with self._install_lock:
            try:
                if component_id == "playwright":
                    _progress(10, 20, "Installing Playwright package…")
                    subprocess.run(
                        [os.environ.get("PYTHON", "python"), "-m", "pip", "install", "playwright"],
                        check=False,
                        timeout=600,
                    )
                    _progress(50, 60, "Installing Chromium…")
                    r = subprocess.run(
                        [os.environ.get("PYTHON", "python"), "-m", "playwright", "install", "chromium"],
                        capture_output=True,
                        text=True,
                        timeout=900,
                    )
                    ok = r.returncode == 0
                elif component_id == "chromium":
                    _progress(20, 40, "Downloading Chromium…")
                    r = subprocess.run(
                        [os.environ.get("PYTHON", "python"), "-m", "playwright", "install", "chromium"],
                        capture_output=True,
                        text=True,
                        timeout=900,
                    )
                    ok = r.returncode == 0
                elif component_id == "ollama":
                    from core.model_runtime import get_model_runtime
                    _progress(5, 10, "Downloading and installing Ollama…")
                    result = get_model_runtime().install_ollama(
                        progress_cb=lambda p: _progress(
                            p.get("download_percent", 50),
                            70,
                            p.get("message", "Installing Ollama…"),
                        )
                    )
                    ok = bool(result.get("ok"))
                    if not ok and result.get("action") == "open_url":
                        return {
                            "ok": False,
                            "action": "open_url",
                            "url": result.get("url", "https://ollama.com/download"),
                            "user_message": result.get("user_message", ""),
                        }
                    return {"ok": ok, "component": self._probe_component(component_id), **result}
                elif component_id == "guardian_tools":
                    _progress(10, 30, "Bootstrapping Guardian tools…")
                    from workers.guardian.bootstrap_manager import run_bootstrap
                    result = run_bootstrap(log_fn=lambda m, l="info": _progress(40, 70, m))
                    ok = bool(result.get("ok", True))
                elif component_id == "vision_stack":
                    r1 = self.install_component("playwright", progress_cb=progress_cb)
                    if not r1.get("ok"):
                        return r1
                    _progress(80, 90, "Optional OCR stack…")
                    subprocess.run(
                        [os.environ.get("PYTHON", "python"), "-m", "pip", "install", "pytesseract", "pillow"],
                        timeout=300,
                    )
                    ok = True
                elif component_id == "builder_godot":
                    from builders.runtime.godot_runtime import install_godot
                    result = install_godot(log_fn=lambda m, l="info": _progress(30, 80, m))
                    ok = bool(result.get("ok"))
                elif component_id == "python_runtime":
                    ok = True
                elif component_id == "update_service":
                    subprocess.run(
                        [os.environ.get("PYTHON", "python"), "-m", "pip", "install", "httpx"],
                        timeout=120,
                    )
                    ok = True
                else:
                    ok = False

                comp = self._probe_component(component_id)
                comp["download_percent"] = 100
                comp["install_percent"] = 100 if ok else comp.get("install_percent", 0)
                comp["status"] = "installed" if ok and comp.get("verification") != "pending" else comp["status"]
                if ok:
                    comp["verification"] = "ok"
                self._state["components"][component_id] = comp
                self._save_state()
                return {"ok": ok, "component": comp}
            except Exception as e:
                logger.exception("install %s", component_id)
                comp = self._state["components"].get(component_id, {})
                comp["status"] = "failed"
                comp["message"] = str(e)[:300]
                comp["verification"] = "failed"
                self._save_state()
                return {"ok": False, "error": str(e), "component": comp}

    def install_all_required(self) -> Dict[str, Any]:
        required = ("playwright", "chromium", "guardian_tools", "vision_stack", "update_service")
        results = {}
        for cid in required:
            comp = self._probe_component(cid)
            if comp.get("status") != "installed" or comp.get("verification") not in ("ok", "partial"):
                results[cid] = self.install_component(cid)
            else:
                results[cid] = {"ok": True, "skipped": True}
        return {"ok": all(r.get("ok") for r in results.values()), "results": results}

    def repair_failed(self) -> Dict[str, Any]:
        repaired = {}
        for cid in COMPONENTS:
            comp = (self._state.get("components") or {}).get(cid) or {}
            if comp.get("status") in ("failed", "missing") or comp.get("verification") == "failed":
                repaired[cid] = self.install_component(cid)
        return {"ok": True, "repaired": repaired}


_mgr: Optional[DependencyManager] = None


def get_dependency_manager() -> DependencyManager:
    global _mgr
    if _mgr is None:
        _mgr = DependencyManager()
    return _mgr
