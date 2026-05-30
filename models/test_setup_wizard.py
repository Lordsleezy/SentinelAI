import db
from models import setup_wizard


def setup_function():
    db.init_db()
    with db.get_conn() as conn:
        conn.execute("DROP TABLE IF EXISTS settings")
        conn.execute("DROP TABLE IF EXISTS model_registry")


def test_is_first_run_true_on_fresh_db():
    assert setup_wizard.is_first_run() is True


def test_is_first_run_false_after_mark_setup_complete():
    setup_wizard.mark_setup_complete()
    assert setup_wizard.is_first_run() is False


def test_run_setup_wizard_returns_correct_tier_for_mocked_hardware(monkeypatch):
    monkeypatch.setattr(
        setup_wizard.hardware_detector,
        "detect_hardware",
        lambda: {"gpu_name": "RTX", "gpu_vram_gb": 12.0, "ram_gb": 32.0, "cpu_cores": 12, "cuda_available": True, "tier": "full"},
    )
    monkeypatch.setattr(setup_wizard, "_download_model", lambda tag: None)
    result = setup_wizard.run_setup_wizard()
    assert result["tier"] == "full"
    assert result["download_started"] is True


def test_models_to_download_list_matches_tier(monkeypatch):
    monkeypatch.setattr(
        setup_wizard.hardware_detector,
        "detect_hardware",
        lambda: {"gpu_name": "CPU", "gpu_vram_gb": 0.0, "ram_gb": 8.0, "cpu_cores": 4, "cuda_available": False, "tier": "minimal"},
    )
    monkeypatch.setattr(setup_wizard, "_download_model", lambda tag: None)
    result = setup_wizard.run_setup_wizard()
    assert [model["model_name"] for model in result["models_to_download"]] == ["sentinel-memory"]


def test_no_crash_if_ollama_unavailable_during_wizard(monkeypatch):
    monkeypatch.setattr(
        setup_wizard.hardware_detector,
        "detect_hardware",
        lambda: {"gpu_name": "CPU", "gpu_vram_gb": 0.0, "ram_gb": 8.0, "cpu_cores": 4, "cuda_available": False, "tier": "minimal"},
    )
    monkeypatch.setattr(setup_wizard, "_download_model", lambda tag: None)
    result = setup_wizard.run_setup_wizard()
    assert result["download_started"] is True
