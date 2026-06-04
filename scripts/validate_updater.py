#!/usr/bin/env python3
"""Updater validation — semver, simulations, live GitHub probe."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RESULTS: list[tuple[str, str, str]] = []


def record(name: str, status: str, detail: str = "") -> None:
    RESULTS.append((name, status, detail))
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))


def test_semver() -> None:
    from core.updater.semver import version_newer

    cases = [
        ("1.0.0-beta.2", "1.0.0-beta.1", True),
        ("1.0.0-beta.10", "1.0.0-beta.9", True),
        ("1.0.1", "1.0.0", True),
        ("1.0.0", "1.0.0-beta.1", True),
        ("1.0.0-beta.1", "1.0.0", False),
        ("1.0.0", "1.0.0", False),
    ]
    for remote, current, expected in cases:
        got = version_newer(remote, current)
        if got != expected:
            record(f"semver {remote}>{current}", "FAIL", f"expected {expected} got {got}")
            return
    record("semver ordering", "PASS", f"{len(cases)} cases")


def test_manifest_file() -> None:
    p = ROOT / "data" / "release" / "update_manifest.json"
    if not p.is_file():
        record("update_manifest.json", "FAIL", "missing")
        return
    m = json.loads(p.read_text(encoding="utf-8"))
    required = (
        "version", "channel", "release_date", "minimum_supported_version",
        "force_update", "kill_switch", "beta_active",
    )
    missing = [k for k in required if k not in m]
    if missing:
        record("update_manifest.json fields", "FAIL", ",".join(missing))
    else:
        record("update_manifest.json fields", "PASS", m.get("version", ""))


def simulate_github_unavailable() -> None:
    from core.updater.auto_updater import AutoUpdater

    u = AutoUpdater()
    with patch.object(u, "test_github_connectivity", return_value={"ok": False, "error": "network down"}):
        r = u.check_for_updates()
    err = (r.get("error") or "").lower()
    if r.get("ok") is False and ("github" in err or "network" in err or "unreachable" in err):
        record("simulate GitHub unavailable", "PASS", r["error"][:60])
    else:
        record("simulate GitHub unavailable", "FAIL", str(r))


def simulate_corrupt_download() -> None:
    from core.updater.auto_updater import AutoUpdater

    u = AutoUpdater()
    state_dir = ROOT / "data" / "updates"
    avail = {
        "version": "v9.9.9-test",
        "body": "SentinelAISetup_test.exe sha256 " + ("a" * 64),
        "asset": {"name": "SentinelAISetup_test.exe", "url": "http://127.0.0.1:9/nope"},
    }
    with patch.object(u, "_expected_checksum", return_value="a" * 64):
        with patch("httpx.Client") as mock_client:
            inst = mock_client.return_value.__enter__.return_value
            stream = MagicMock()
            stream.__enter__.return_value = stream
            stream.iter_bytes.return_value = [b"corrupt-bytes"]
            stream.raise_for_status = MagicMock()
            inst.stream.return_value = stream
            r = u._download_worker(avail)
    if not r.get("ok") and "checksum" in (r.get("error") or "").lower():
        record("simulate corrupt update", "PASS", r.get("error"))
    else:
        record("simulate corrupt update", "FAIL", str(r))


def simulate_interrupted_download() -> None:
    from core.updater.auto_updater import AutoUpdater

    u = AutoUpdater()
    avail = {
        "version": "v9.9.8-test",
        "body": "",
        "asset": {"name": "interrupt.exe", "url": "http://example.invalid/x"},
    }
    with patch("httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.stream.side_effect = Exception("connection reset")
        r = u._download_worker(avail)
    part = list((ROOT / "data" / "updates").glob("pending_v9.9.8-test_interrupt.exe.part"))
    if not r.get("ok") and not part:
        record("simulate interrupted download", "PASS", "no orphan .part")
    elif not r.get("ok"):
        record("simulate interrupted download", "WARNING", f"part left: {part}")
    else:
        record("simulate interrupted download", "FAIL", str(r))


def simulate_failed_install() -> None:
    from core.updater.auto_updater import AutoUpdater

    u = AutoUpdater()
    u._touch_state(pending_download={
        "path": str(ROOT / "data" / "updates" / "nonexistent_installer.exe"),
        "version": "v0.0.0",
        "sha256": "00" * 32,
    })
    r = u.install_pending()
    if not r.get("ok"):
        record("simulate failed install", "PASS", r.get("error", "")[:60])
    else:
        record("simulate failed install", "FAIL", str(r))


def simulate_rollback_trigger() -> None:
    from core.updater.auto_updater import AutoUpdater

    u = AutoUpdater()
    u._touch_state(rollback_version="1.0.0-beta.1")
    info = u.rollback_info()
    if info.get("rollback_version"):
        record("rollback metadata", "PASS", info.get("rollback_version"))
    else:
        record("rollback metadata", "FAIL", str(info))


def test_live_github() -> None:
    from core.updater import get_auto_updater

    u = get_auto_updater()
    gh = u.test_github_connectivity()
    if gh.get("ok"):
        record("live GitHub connectivity", "PASS", f"HTTP {gh.get('status_code')}")
    else:
        record("live GitHub connectivity", "WARNING", gh.get("error", "unreachable"))


def test_live_check() -> None:
    from core.updater import get_auto_updater

    chk = get_auto_updater().check_for_updates()
    if chk.get("ok"):
        av = chk.get("available")
        record("live update check", "PASS", (av or {}).get("version", "up to date"))
    else:
        record("live update check", "WARNING", chk.get("error", ""))


def write_report() -> None:
    out = ROOT / "UPDATER_VALIDATION_REPORT.md"
    lines = [
        "# Updater Validation Report",
        "",
        f"**Generated:** {__import__('datetime').datetime.utcnow().isoformat()}Z",
        "",
        "| Check | Status | Detail |",
        "|-------|--------|--------|",
    ]
    for name, status, detail in RESULTS:
        lines.append(f"| {name} | {status} | {detail.replace('|', '/')} |")
    fails = sum(1 for _, s, _ in RESULTS if s == "FAIL")
    warns = sum(1 for _, s, _ in RESULTS if s == "WARNING")
    lines.extend([
        "",
        f"**Summary:** {len(RESULTS)} checks, {fails} FAIL, {warns} WARNING",
        "",
    ])
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {out}")


def main() -> int:
    test_semver()
    test_manifest_file()
    simulate_github_unavailable()
    simulate_corrupt_download()
    simulate_interrupted_download()
    simulate_failed_install()
    simulate_rollback_trigger()
    test_live_github()
    test_live_check()
    write_report()
    return 1 if any(s == "FAIL" for _, s, _ in RESULTS) else 0


if __name__ == "__main__":
    raise SystemExit(main())
