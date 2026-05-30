import db
import orchestrator
from models import hardware_detector, model_manager, model_registry, setup_wizard


class FakeResponse:
    status_code = 200

    def __init__(self, payload=None):
        self.payload = payload or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def setup_function():
    db.init_db()
    with db.get_conn() as conn:
        conn.execute("DROP TABLE IF EXISTS settings")
        conn.execute("DROP TABLE IF EXISTS model_registry")
    model_registry.init_registry()


def test_full_model_pipeline(monkeypatch):
    assert setup_wizard.is_first_run() is True

    monkeypatch.setattr(
        hardware_detector,
        "detect_hardware",
        lambda: {"gpu_name": "RTX", "gpu_vram_gb": 12.0, "ram_gb": 32.0, "cpu_cores": 12, "cuda_available": True, "tier": "full"},
    )
    monkeypatch.setattr(
        setup_wizard.hardware_detector,
        "detect_hardware",
        hardware_detector.detect_hardware,
    )
    monkeypatch.setattr(setup_wizard, "_download_model", lambda tag: None)

    hardware = hardware_detector.detect_hardware()
    assert hardware["tier"] in {"minimal", "basic", "standard", "full", "unlimited"}

    tier_models = model_registry.get_models_for_tier(hardware["tier"])
    assert tier_models

    model_registry.mark_downloaded("qwen2.5-coder:14b", True)
    model_registry.mark_downloaded("qwen3:8b", True)
    assert model_manager.get_model_for_task("code") == "qwen2.5-coder:14b"
    assert model_manager.get_model_for_task("chat") == "qwen3:8b"

    calls = []
    monkeypatch.setattr(model_manager, "get_loaded_models", lambda: ["deepseek-r1:8b"])
    monkeypatch.setattr(model_manager, "unload_model", lambda tag: calls.append(("unload", tag)) or True)
    monkeypatch.setattr(model_manager, "ensure_model_loaded", lambda tag: calls.append(("load", tag)) or True)
    assert model_manager.smart_swap("qwen2.5-coder:14b", hardware) is True

    setup_wizard.run_setup_wizard()
    assert setup_wizard.is_first_run() is False

    import desktop_app

    response = desktop_app.app.test_client().get("/api/models/status")
    body = response.get_json()
    assert response.status_code == 200 and {"loaded", "models"} <= set(body["data"])

    captured = []

    def fake_post(_url, json=None, timeout=None):
        captured.append(json["model"])
        return FakeResponse({"response": '{"intent":"build","target":"function","parameters":{}}'})

    import httpx
    monkeypatch.setattr(orchestrator, "_ollama_available", lambda: True)
    monkeypatch.setattr(httpx, "post", fake_post)
    orchestrator.parse_intent("write me a function")
    assert captured[-1] == "qwen2.5-coder:14b"
