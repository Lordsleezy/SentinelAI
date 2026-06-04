"""Model runtime — Ollama detection, install, pull, validation, self-healing."""
from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("sentinel.model_runtime")

from core.app_paths import resolve_data_path

_STATE_PATH = resolve_data_path("model_runtime", "state.json")
_READY_PATH = resolve_data_path("model_runtime", "ready.json")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_WIN_INSTALLER = "https://ollama.com/download/OllamaSetup.exe"

_USER_MESSAGES = {
    "installing_ollama": "Setting up the local AI runtime. This may take a few minutes.",
    "starting_ollama": "Starting the local AI service…",
    "downloading_models": "Downloading language models for your hardware…",
    "validating": "Running a quick test to confirm everything works…",
    "ready": "Sentinel is ready.",
    "offline": "Sentinel is reconnecting to the local AI service. Please wait a moment.",
    "repair_failed": "Sentinel could not restore the local AI service automatically. Open Settings → Models to retry setup.",
    "not_ready": "Sentinel is still setting up local AI. Complete setup in the wizard, or wait for downloads to finish.",
}

_lock = threading.Lock()
_heal_lock = threading.Lock()


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _friendly(code: str) -> str:
    return _USER_MESSAGES.get(code, _USER_MESSAGES["not_ready"])


class ModelRuntime:
    def __init__(self) -> None:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load_state()
        self._pull_proc: Optional[subprocess.Popen] = None

    def _load_state(self) -> Dict[str, Any]:
        if _STATE_PATH.is_file():
            try:
                return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "phase": "idle",
            "message": "",
            "pull": {},
            "install": {},
            "last_heal": None,
            "last_validation": None,
        }

    def _save_state(self) -> None:
        _STATE_PATH.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    def _load_ready(self) -> Dict[str, Any]:
        if _READY_PATH.is_file():
            try:
                return json.loads(_READY_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_ready(self, payload: Dict[str, Any]) -> None:
        _READY_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # ── Detection ─────────────────────────────────────────────────────────

    def ollama_installed(self) -> bool:
        if shutil.which("ollama"):
            return True
        win = self._windows_ollama_exe()
        return win is not None and win.is_file()

    def _windows_ollama_exe(self) -> Optional[Path]:
        if platform.system() != "Windows":
            return None
        local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama"
        for name in ("ollama.exe", "Ollama.exe"):
            p = local / name
            if p.is_file():
                return p
        return None

    def ollama_running(self) -> bool:
        try:
            import httpx
            r = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    def list_installed_models(self) -> Dict[str, str]:
        """HTTP only — never call `ollama list` (CLI can hang on Windows)."""
        try:
            import httpx
            r = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
            if r.status_code != 200:
                return {}
            out = {}
            for m in r.json().get("models", []):
                name = m.get("name", "")
                if name:
                    out[name] = m.get("digest", "")[:12]
            return out
        except Exception:
            return {}

    def required_models(self, *, quick: bool = False) -> Dict[str, Any]:
        if quick:
            try:
                from workers.setup.machine_scanner import get_machine_scanner
                from core.onboarding.hardware_probe import recommend_models_fast
                cached = get_machine_scanner().load_cached() or {}
                if cached.get("recommended"):
                    return cached["recommended"]
                return recommend_models_fast(
                    float(cached.get("ram_gb") or 8),
                    float(cached.get("vram_gb") or 0),
                )
            except Exception:
                pass
        try:
            from core.model_manager import get_model_manager
            rec = get_model_manager().recommend()
        except Exception:
            from core.onboarding.hardware_probe import recommend_models_fast
            rec = recommend_models_fast(8.0, 0.0)
        llama = rec.get("llama") or "llama3.2:3b"
        dolphin = rec.get("dolphin")
        required = [{"name": llama, "role": "llama", "required": True}]
        if dolphin:
            required.append({"name": dolphin, "role": "dolphin", "required": True})
        return {"llama": llama, "dolphin": dolphin, "models": required, "recommendation": rec}

    @staticmethod
    def _model_present(tag: str, installed: Dict[str, str]) -> bool:
        if tag in installed:
            return True
        base = tag.split(":")[0].lower()
        for k in installed:
            kl = k.lower()
            if kl == tag.lower() or kl.startswith(tag.lower() + ":"):
                return True
            if kl.split(":")[0] == base:
                return True
        return False

    def models_status(self, *, quick: bool = False) -> List[Dict[str, Any]]:
        from core.model_manager.engine import CATALOG
        installed = self.list_installed_models()
        req = self.required_models(quick=quick)
        out = []
        for entry in req["models"]:
            name = entry["name"]
            meta = CATALOG.get(name, {})
            out.append({
                "name": name,
                "role": entry["role"],
                "size_gb": meta.get("size_gb"),
                "installed": self._model_present(name, installed),
                "required": entry["required"],
            })
        return out

    def active_chat_model(self) -> str:
        ready = self._load_ready()
        if ready.get("chat_model"):
            return ready["chat_model"]
        req = self.required_models()
        if req.get("dolphin"):
            return req["dolphin"]
        return req["llama"]

    def apply_active_model_env(self) -> None:
        model = self.active_chat_model()
        os.environ["OLLAMA_MODEL"] = model
        os.environ.setdefault("OLLAMA_HOST", OLLAMA_HOST)

    # ── Install / start Ollama ────────────────────────────────────────────

    def ensure_ollama_running(self) -> Dict[str, Any]:
        if self.ollama_running():
            return {"ok": True, "action": "already_running"}
        self._state["phase"] = "starting_ollama"
        self._state["message"] = _friendly("starting_ollama")
        self._save_state()

        exe = shutil.which("ollama") or (str(self._windows_ollama_exe()) if self._windows_ollama_exe() else None)
        if exe:
            try:
                if platform.system() == "Windows":
                    win_app = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "Ollama.exe"
                    if win_app.is_file():
                        subprocess.Popen(
                            [str(win_app)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                subprocess.Popen(
                    [exe, "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception as e:
                logger.warning("start ollama serve: %s", e)

        deadline = time.time() + 90
        while time.time() < deadline:
            if self.ollama_running():
                return {"ok": True, "action": "started"}
            time.sleep(2)
        return {"ok": False, "action": "start_timeout", "user_message": _friendly("offline")}

    def install_ollama_windows(
        self,
        progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        if platform.system() != "Windows":
            return {
                "ok": False,
                "user_message": "Automatic Ollama install is available on Windows. Download from ollama.com on other platforms.",
                "action": "open_url",
                "url": "https://ollama.com/download",
            }
        if self.ollama_installed():
            return self.ensure_ollama_running()

        self._state["phase"] = "installing_ollama"
        self._state["message"] = _friendly("installing_ollama")
        self._state["install"] = {"download_percent": 0, "started_at": _utc()}
        self._save_state()

        dest = resolve_data_path("model_runtime", "OllamaSetup.exe")
        dest.parent.mkdir(parents=True, exist_ok=True)

        try:
            import httpx
            with httpx.stream("GET", OLLAMA_WIN_INSTALLER, follow_redirects=True, timeout=120) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length") or 0)
                done = 0
                with dest.open("wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        f.write(chunk)
                        done += len(chunk)
                        pct = int(done * 100 / total) if total else min(95, done // 500000)
                        self._state["install"]["download_percent"] = pct
                        self._save_state()
                        if progress_cb:
                            progress_cb({"download_percent": pct, "message": "Downloading Ollama installer…"})
        except Exception as e:
            logger.exception("ollama download")
            return {"ok": False, "error": str(e)[:200], "user_message": _friendly("repair_failed")}

        self._state["install"]["download_percent"] = 100
        self._state["install"]["message"] = "Installing Ollama…"
        self._save_state()
        if progress_cb:
            progress_cb({"download_percent": 100, "message": "Installing Ollama…"})

        for flag in ("/SILENT", "/VERYSILENT", "/S"):
            try:
                proc = subprocess.run(
                    [str(dest), flag],
                    timeout=600,
                    capture_output=True,
                )
                if proc.returncode == 0:
                    break
            except Exception:
                continue

        # Refresh PATH for current process
        local_bin = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama"
        if local_bin.is_dir():
            os.environ["PATH"] = str(local_bin) + os.pathsep + os.environ.get("PATH", "")

        deadline = time.time() + 120
        while time.time() < deadline:
            if self.ollama_installed():
                return self.ensure_ollama_running()
            time.sleep(3)

        return {"ok": False, "user_message": _friendly("repair_failed")}

    def install_ollama(self, progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
        if self.ollama_installed():
            return self.ensure_ollama_running()
        if platform.system() == "Windows":
            return self.install_ollama_windows(progress_cb)
        return {
            "ok": False,
            "action": "open_url",
            "url": "https://ollama.com/download",
            "user_message": "Install Ollama from ollama.com, then return to Sentinel to continue setup.",
        }

    # ── Model pull with progress ──────────────────────────────────────────

    def _parse_pull_percent(self, line: str) -> Optional[int]:
        m = re.search(r"(\d+)\s*%", line)
        return int(m.group(1)) if m else None

    def pull_model(
        self,
        model_name: str,
        progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        if not self.ollama_running():
            start = self.ensure_ollama_running()
            if not start.get("ok"):
                return {"ok": False, "user_message": start.get("user_message", _friendly("offline"))}

        from core.model_manager.engine import CATALOG
        size_gb = CATALOG.get(model_name, {}).get("size_gb", 0)
        self._state["phase"] = "downloading_models"
        self._state["pull"] = {
            "model": model_name,
            "size_gb": size_gb,
            "percent": 0,
            "message": f"Downloading {model_name}…",
            "started_at": _utc(),
        }
        self._save_state()

        try:
            proc = subprocess.Popen(
                ["ollama", "pull", model_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            self._pull_proc = proc
            last_pct = 0
            for line in iter(proc.stdout.readline, ""):
                line = line.strip()
                if not line:
                    continue
                pct = self._parse_pull_percent(line) or last_pct
                last_pct = max(last_pct, pct)
                self._state["pull"]["percent"] = last_pct
                self._state["pull"]["message"] = line[:200]
                self._save_state()
                if progress_cb:
                    progress_cb(dict(self._state["pull"]))
            proc.wait(timeout=3600)
            ok = proc.returncode == 0
            self._pull_proc = None
            self._state["pull"]["percent"] = 100 if ok else last_pct
            self._state["pull"]["complete"] = ok
            self._save_state()
            return {"ok": ok, "model": model_name, "user_message": _friendly("ready") if ok else _friendly("repair_failed")}
        except FileNotFoundError:
            return {"ok": False, "user_message": _friendly("repair_failed")}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200], "user_message": _friendly("repair_failed")}

    def install_required_models(
        self,
        progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        installed = self.list_installed_models()
        req = self.required_models()
        results = {}
        for entry in req["models"]:
            name = entry["name"]
            if self._model_present(name, installed):
                results[name] = {"ok": True, "skipped": True}
                continue
            results[name] = self.pull_model(name, progress_cb=progress_cb)
            if not results[name].get("ok"):
                return {"ok": False, "results": results, "user_message": results[name].get("user_message")}
            installed = self.list_installed_models()
        return {"ok": True, "results": results}

    # ── Validation ────────────────────────────────────────────────────────

    def validate_inference(self) -> Dict[str, Any]:
        self._state["phase"] = "validating"
        self._state["message"] = _friendly("validating")
        self._save_state()

        if not self.ollama_running():
            return {"ok": False, "user_message": _friendly("offline"), "cause": "ollama_unreachable"}

        model = self.active_chat_model()
        if not self._model_present(model, self.list_installed_models()):
            req = self.required_models()
            model = req.get("llama") or model

        try:
            import httpx
            with httpx.Client(timeout=90.0) as client:
                r = client.post(
                    f"{OLLAMA_HOST}/api/generate",
                    json={
                        "model": model,
                        "prompt": "Reply with exactly the word READY and nothing else.",
                        "stream": False,
                        "options": {"num_predict": 16},
                    },
                )
            if r.status_code != 200:
                return {
                    "ok": False,
                    "cause": "inference_http_error",
                    "user_message": _friendly("repair_failed"),
                }
            text = (r.json().get("response") or "").strip()
            if len(text) < 2:
                return {"ok": False, "cause": "empty_response", "user_message": _friendly("repair_failed")}
            payload = {
                "ok": True,
                "chat_model": model,
                "validated_at": _utc(),
                "sample": text[:80],
            }
            self._save_ready(payload)
            self.apply_active_model_env()
            self._state["last_validation"] = payload
            self._state["phase"] = "ready"
            self._state["message"] = _friendly("ready")
            self._save_state()
            return payload
        except Exception as e:
            logger.warning("validate_inference: %s", e)
            return {"ok": False, "cause": "inference_exception", "user_message": _friendly("repair_failed")}

    # ── Readiness & heal ──────────────────────────────────────────────────

    @staticmethod
    def _status_message(
        *,
        ready: bool,
        ollama_installed: bool,
        ollama_running: bool,
        all_required_models: bool,
        validated: bool,
    ) -> str:
        if ready:
            return _friendly("ready")
        if not ollama_installed:
            return _friendly("installing_ollama")
        if not ollama_running:
            return _friendly("starting_ollama")
        if not all_required_models:
            return _friendly("downloading_models")
        if not validated:
            return _friendly("validating")
        return _friendly("not_ready")

    def readiness_quick(self) -> Dict[str, Any]:
        """Fast readiness for onboarding UI — no blocking subprocesses."""
        req = self.required_models(quick=True)
        ollama_installed = self.ollama_installed()
        ollama_running = self.ollama_running() if ollama_installed else False
        models = self.models_status(quick=True)
        all_models = all(m["installed"] for m in models if m["required"])
        validated = bool(self._load_ready().get("ok"))
        ready = ollama_installed and ollama_running and all_models and validated
        user_message = self._status_message(
            ready=ready,
            ollama_installed=ollama_installed,
            ollama_running=ollama_running,
            all_required_models=all_models,
            validated=validated,
        )
        return {
            "ready": ready,
            "allow_chat": True,
            "ollama_installed": ollama_installed,
            "ollama_running": ollama_running,
            "models": models,
            "all_required_models": all_models,
            "validated": validated,
            "required": req,
            "user_message": user_message,
            "degraded": not ready,
        }

    def readiness(self) -> Dict[str, Any]:
        req = self.required_models(quick=True)
        ollama_installed = self.ollama_installed()
        ollama_running = self.ollama_running() if ollama_installed else False
        models = self.models_status(quick=True)
        all_models = all(m["installed"] for m in models if m["required"])
        validated = bool(self._load_ready().get("ok"))
        ready = ollama_installed and ollama_running and all_models and validated
        phase = self._state.get("phase", "idle")
        user_message = self._status_message(
            ready=ready,
            ollama_installed=ollama_installed,
            ollama_running=ollama_running,
            all_required_models=all_models,
            validated=validated,
        )
        return {
            "ready": ready,
            "allow_chat": True,
            "ollama_installed": ollama_installed,
            "ollama_running": ollama_running,
            "models": models,
            "all_required_models": all_models,
            "validated": validated,
            "chat_model": self.active_chat_model() if validated else req.get("dolphin") or req.get("llama"),
            "required": req,
            "phase": phase,
            "message": self._state.get("message") or user_message,
            "pull": self._state.get("pull") or {},
            "install": self._state.get("install") or {},
            "user_message": user_message,
            "degraded": not ready,
        }

    def is_ready(self) -> bool:
        return bool(self.readiness().get("ready"))

    def user_message(self) -> str:
        r = self.readiness()
        return r.get("user_message") or _friendly("not_ready")

    def heal(self, max_retries: int = 2) -> Dict[str, Any]:
        with _heal_lock:
            attempts = []
            for i in range(max_retries):
                if not self.ollama_installed():
                    attempts.append(("install_ollama", self.install_ollama()))
                elif not self.ollama_running():
                    attempts.append(("start_ollama", self.ensure_ollama_running()))
                r = self.readiness()
                if not r["all_required_models"]:
                    attempts.append(("pull_models", self.install_required_models()))
                val = self.validate_inference()
                attempts.append(("validate", val))
                if val.get("ok"):
                    self._state["last_heal"] = {"ok": True, "at": _utc(), "attempts": len(attempts)}
                    self._save_state()
                    return {"ok": True, "readiness": self.readiness(), "user_message": _friendly("ready")}
                time.sleep(2)
            self._state["last_heal"] = {"ok": False, "at": _utc()}
            self._save_state()
            return {
                "ok": False,
                "readiness": self.readiness(),
                "user_message": self.user_message(),
                "attempts": len(attempts),
            }

    def mark_setup_complete(self) -> Dict[str, Any]:
        from core.onboarding.pipeline import get_onboarding_pipeline
        return get_onboarding_pipeline().force_complete(allow_degraded=True)


_runtime: Optional[ModelRuntime] = None


def get_model_runtime() -> ModelRuntime:
    global _runtime
    if _runtime is None:
        _runtime = ModelRuntime()
    return _runtime


def start_self_healing_monitor(interval_sec: int = 45) -> None:
    """Background thread: detect Ollama loss and repair without raw errors."""

    def _loop() -> None:
        rt = get_model_runtime()
        was_ready = rt.is_ready()
        while True:
            try:
                time.sleep(interval_sec)
                if rt.is_ready():
                    was_ready = True
                    continue
                if was_ready or rt.ollama_installed():
                    logger.info("Ollama/model health degraded — healing")
                    rt._state["message"] = _friendly("offline")
                    rt._save_state()
                    result = rt.heal(max_retries=1)
                    if result.get("ok"):
                        logger.info("Self-heal restored model runtime")
                    was_ready = result.get("ok", False)
            except Exception:
                logger.debug("self-heal loop", exc_info=True)

    t = threading.Thread(target=_loop, name="model-self-heal", daemon=True)
    t.start()
