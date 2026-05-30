import json

import db
import orchestrator
from models import model_registry, setup_wizard


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
        conn.execute("DROP TABLE IF EXISTS model_registry")
        conn.execute("DROP TABLE IF EXISTS settings")
    model_registry.init_registry()


def test_models_status_endpoint_returns_envelope(monkeypatch):
    import desktop_app

    monkeypatch.setattr("models.model_manager.get_loaded_models", lambda: ["qwen3:8b"])
    response = desktop_app.app.test_client().get("/api/models/status")
    body = response.get_json()
    assert response.status_code == 200
    assert {"status", "data", "error"} <= set(body)
    assert "loaded" in body["data"]
    assert "models" in body["data"]


def test_setup_status_complete_and_incomplete(monkeypatch):
    import desktop_app

    monkeypatch.setattr(
        "models.hardware_detector.detect_hardware",
        lambda: {"gpu_name": "CPU", "gpu_vram_gb": 0.0, "ram_gb": 8.0, "cpu_cores": 4, "cuda_available": False, "tier": "minimal"},
    )
    client = desktop_app.app.test_client()
    assert client.get("/api/setup/status").get_json()["data"]["complete"] is False
    setup_wizard.mark_setup_complete()
    assert client.get("/api/setup/status").get_json()["data"]["complete"] is True


def test_orchestrator_uses_coder_for_code_and_brain_for_chat(monkeypatch):
    for tag in ["qwen3:8b", "qwen2.5-coder:14b"]:
        model_registry.mark_downloaded(tag, True)
    captured = []

    def fake_post(_url, json=None, timeout=None):
        captured.append(json["model"])
        return FakeResponse({"response": '{"intent":"build","target":"x","parameters":{}}'})

    monkeypatch.setattr(orchestrator, "_ollama_available", lambda: True)
    monkeypatch.setattr(orchestrator, "httpx", None, raising=False)
    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)

    orchestrator.parse_intent("write me a function")
    assert json.loads('{"ok": true}')["ok"] is True
    assert captured[-1] == "qwen2.5-coder:14b"

    def fake_post_chat(_url, json=None, timeout=None):
        captured.append(json["model"])
        return FakeResponse({"response": '{"intent":"unknown","target":"hello","parameters":{}}'})

    monkeypatch.setattr(httpx, "post", fake_post_chat)
    orchestrator.parse_intent("hello there")
    assert captured[-1] == "qwen3:8b"
