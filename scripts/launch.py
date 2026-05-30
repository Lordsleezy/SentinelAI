from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from revenue import bounty_pipeline
from tools import registry
from models import hardware_detector, model_registry, setup_wizard


def check_ollama() -> str:
    try:
        response = requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
        return "connected" if response.status_code == 200 else "offline"
    except Exception:
        return "offline"


def wait_for_backend(timeout=20) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = requests.get("http://127.0.0.1:5001/api/status", timeout=1)
            if response.status_code == 200:
                return True
        except Exception:
            time.sleep(0.5)
    return False


def run_pipeline_background(state: dict) -> None:
    try:
        result = bounty_pipeline.run_pipeline_cycle()
        state["pipeline"] = result
    except Exception as exc:
        state["pipeline_error"] = str(exc)


def print_summary(backend_running: bool, ollama_status: str, pipeline_result: dict | None = None, hardware: dict | None = None) -> None:
    workers = registry.list_tools()
    model_registry.init_registry()
    downloaded = model_registry.get_downloaded_models()
    all_models = model_registry.get_all_models()
    queued = 0
    if pipeline_result:
        queued = pipeline_result.get("queued", 0)
    print(f"Backend: {'running on port 5001' if backend_running else 'offline'}")
    print(f"Workers: {', '.join(tool['tool_name'] for tool in workers) if workers else 'none'}")
    print(f"Ollama: {ollama_status}")
    if hardware:
        print(f"Hardware tier: {hardware.get('tier')} ({hardware.get('gpu_name')} {hardware.get('gpu_vram_gb')}GB VRAM)")
    print(f"Models downloaded: {len(downloaded)}/{len(all_models)}")
    pending = [model["ollama_tag"] for model in all_models if not model["downloaded"]]
    print(f"Models pending: {', '.join(pending) if pending else 'none'}")
    print(f"Pipeline: queued count {queued}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch SentinelAI fallback runtime")
    parser.add_argument("--dry-run", action="store_true", help="Print launch status and exit")
    args = parser.parse_args()

    ollama_status = check_ollama()
    if ollama_status != "connected":
        print("Warning: Ollama is offline; continuing anyway.")

    registry.register_builtin_tools()
    model_registry.init_registry()
    hardware = hardware_detector.detect_hardware()

    if args.dry_run:
        print_summary(False, ollama_status, {"queued": 0}, hardware)
        return 0

    if setup_wizard.is_first_run():
        setup_wizard.run_setup_wizard()

    import desktop_app

    backend_thread = threading.Thread(target=desktop_app.start_backend, daemon=True)
    backend_thread.start()
    backend_running = wait_for_backend()

    pipeline_state: dict = {}
    pipeline_thread = threading.Thread(target=run_pipeline_background, args=(pipeline_state,), daemon=True)
    pipeline_thread.start()
    pipeline_thread.join(timeout=5)

    print_summary(backend_running, ollama_status, pipeline_state.get("pipeline"), hardware)
    print("SentinelAI launch script running. Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping SentinelAI launcher.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
