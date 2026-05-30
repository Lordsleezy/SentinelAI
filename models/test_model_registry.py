import db
from models import model_registry


def setup_function():
    db.init_db()
    with db.get_conn() as conn:
        conn.execute("DROP TABLE IF EXISTS model_registry")


def test_init_seeds_5_models():
    model_registry.init_registry()
    assert len(model_registry.get_all_models()) == 5


def test_get_model_for_task_code_returns_coder():
    assert model_registry.get_model_for_task("code")["model_name"] == "sentinel-coder"


def test_get_model_for_task_chat_returns_brain():
    assert model_registry.get_model_for_task("chat")["model_name"] == "sentinel-brain"


def test_get_models_for_tier_standard_excludes_more_than_12gb():
    models = model_registry.get_models_for_tier("standard")
    assert models
    assert all(model["min_vram_gb"] <= 12.0 for model in models)


def test_mark_downloaded_updates_db():
    model_registry.mark_downloaded("qwen3:8b", True)
    downloaded = model_registry.get_downloaded_models()
    assert [model["ollama_tag"] for model in downloaded] == ["qwen3:8b"]
    assert downloaded[0]["download_progress"] == 100.0
