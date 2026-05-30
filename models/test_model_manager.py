import pytest

import db
from models import model_manager, model_registry


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self.payload = payload or {}
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("bad response")

    def json(self):
        return self.payload


def setup_function():
    db.init_db()
    with db.get_conn() as conn:
        conn.execute("DROP TABLE IF EXISTS model_registry")
    model_registry.init_registry()
    for tag in ["qwen3:8b", "qwen2.5-coder:14b", "deepseek-r1:8b", "llava:7b", "nomic-embed-text"]:
        model_registry.mark_downloaded(tag, True)


def test_get_model_for_task_routes_correctly():
    assert model_manager.get_model_for_task("code") == "qwen2.5-coder:14b"
    assert model_manager.get_model_for_task("chat") == "qwen3:8b"
    assert model_manager.get_model_for_task("reason") == "deepseek-r1:8b"
    assert model_manager.get_model_for_task("vision") == "llava:7b"
    assert model_manager.get_model_for_task("embed") == "nomic-embed-text"


def test_fallback_to_brain_when_model_not_downloaded():
    model_registry.mark_downloaded("qwen2.5-coder:14b", False)
    assert model_manager.get_model_for_task("code") == "qwen3:8b"


def test_smart_swap_unloads_lru_before_loading_new_model(monkeypatch):
    calls = []
    monkeypatch.setattr(model_manager, "get_loaded_models", lambda: ["deepseek-r1:8b"])
    monkeypatch.setattr(model_manager, "unload_model", lambda tag: calls.append(("unload", tag)) or True)
    monkeypatch.setattr(model_manager, "ensure_model_loaded", lambda tag: calls.append(("load", tag)) or True)
    assert model_manager.smart_swap("qwen2.5-coder:14b", {"gpu_vram_gb": 9.0, "tier": "standard"}) is True
    assert calls == [("unload", "deepseek-r1:8b"), ("load", "qwen2.5-coder:14b")]


def test_generate_raises_model_unavailable_when_ollama_offline(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(model_manager.requests, "post", fail)
    with pytest.raises(model_manager.ModelUnavailableError):
        model_manager.generate("qwen3:8b", "hello")
