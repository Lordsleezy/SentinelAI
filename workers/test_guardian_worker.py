from pathlib import Path

from workers.guardian_worker import check_api_key_exposure, scan_file


def test_scan_file_detects_eicar(tmp_path, monkeypatch):
    sample = tmp_path / "eicar.txt"
    sample.write_text("placeholder")
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda self: b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*",
    )
    result = scan_file(sample)
    assert result["clean"] is False
    assert "EICAR-Test-File" in result["threats"]


def test_scan_file_passes_clean_file(tmp_path):
    sample = tmp_path / "clean.txt"
    sample.write_text("hello world")
    assert scan_file(sample)["clean"] is True


def test_check_api_key_exposure_detects_fake_patterns():
    text = "AWS AKIAABCDEFGHIJKLMNOP GitHub ghp_abcdefghijklmnopqrstuvwxyz Anthropic sk-ant-abcdefghijklmnopqrstuvwxyz"
    found = check_api_key_exposure(text)
    types = {item["type"] for item in found}
    assert {"aws_access_key", "github_token", "anthropic_key"} <= types


def test_clean_text_passes():
    assert check_api_key_exposure("nothing sensitive here") == []
