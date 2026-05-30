from models import hardware_detector


def test_detect_hardware_returns_required_fields():
    info = hardware_detector.detect_hardware()
    assert {"gpu_name", "gpu_vram_gb", "ram_gb", "cpu_cores", "cuda_available", "tier"} <= set(info)
    assert isinstance(info["gpu_vram_gb"], float)
    assert info["tier"] in {"minimal", "basic", "standard", "full", "unlimited"}


def test_tier_assigned_for_each_vram_range():
    assert hardware_detector.tier_for_vram(0) == "minimal"
    assert hardware_detector.tier_for_vram(5.9) == "minimal"
    assert hardware_detector.tier_for_vram(6) == "basic"
    assert hardware_detector.tier_for_vram(8) == "standard"
    assert hardware_detector.tier_for_vram(12) == "full"
    assert hardware_detector.tier_for_vram(16) == "unlimited"


def test_no_crash_if_nvidia_smi_unavailable(monkeypatch):
    monkeypatch.setattr(hardware_detector, "_detect_with_torch", lambda: None)
    monkeypatch.setattr(hardware_detector, "_detect_with_nvidia_smi", lambda: None)
    info = hardware_detector.detect_hardware()
    assert info["gpu_name"] == "CPU only"
    assert info["tier"] == "minimal"


def test_vram_gb_is_float(monkeypatch):
    monkeypatch.setattr(hardware_detector, "_detect_with_torch", lambda: None)
    monkeypatch.setattr(hardware_detector, "_detect_with_nvidia_smi", lambda: {"gpu_name": "RTX", "gpu_vram_gb": 8})
    assert isinstance(hardware_detector.detect_hardware()["gpu_vram_gb"], float)
