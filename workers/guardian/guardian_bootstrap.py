"""
Guardian bootstrap — verify and repair bundled core tools on startup.

Copies from installer_assets/guardian_core/<tool>/ into tools/<tool>/ when missing.
Runs once per Sentinel version (or when repair is requested).
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from workers.guardian.bundled_toolchain import (
    CORE_TOOL_IDS,
    diagnose_core_tool,
    get_bundled_exe_path,
    get_bundled_tool_dir,
    get_installer_assets_dir,
    get_sentinel_root,
    resolve_tool_binary,
)

logger = logging.getLogger(__name__)

_MANIFEST_NAME = "manifest.json"
_STATE_REL = Path("memory") / "vault" / "guardian_bootstrap.json"


def _state_path() -> Path:
    return get_sentinel_root() / _STATE_REL


def _load_manifest() -> Dict[str, Any]:
    for base in (
        get_sentinel_root() / "installer_assets" / "guardian_core",
        Path(__file__).resolve().parents[2] / "installer_assets" / "guardian_core",
    ):
        mf = base / _MANIFEST_NAME
        if mf.is_file():
            try:
                return json.loads(mf.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("[GUARDIAN/bootstrap] manifest read failed: %s", e)
    return {
        "version": 1,
        "tools": [
            {"id": "httpx", "exe": "httpx.exe", "zip": "httpx_windows_amd64.zip"},
            {"id": "subfinder", "exe": "subfinder.exe", "zip": "subfinder_windows_amd64.zip"},
            {"id": "katana", "exe": "katana.exe", "zip": "katana_windows_amd64.zip"},
            {"id": "nuclei", "exe": "nuclei.exe", "zip": "nuclei_windows_amd64.zip"},
        ],
    }


def _log(msg: str, level: str = "info", log_fn: Optional[Callable[[str, str], None]] = None) -> None:
    text = msg if msg.startswith("[GUARDIAN]") else f"[GUARDIAN] {msg}"
    lvl = logging.INFO if level in ("info", "success") else (
        logging.WARNING if level == "warning" else logging.ERROR
    )
    logger.log(lvl, text)
    if log_fn:
        try:
            log_fn(text, level)
        except Exception:
            pass


def _verify_binary(exe: Path, timeout: int = 12) -> bool:
    if not exe.is_file():
        return False
    for flag in ("-version", "-h", "--help"):
        try:
            proc = subprocess.run(
                [str(exe), flag],
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            if proc.returncode == 0 or (proc.stdout or proc.stderr):
                return True
        except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
            continue
    return exe.stat().st_size > 50_000


def _extract_zip(zip_path: Path, dest_dir: Path, exe_name: str) -> Optional[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)
    # Flatten: find exe anywhere under dest_dir
    direct = dest_dir / exe_name
    if direct.is_file():
        return direct
    for p in dest_dir.rglob(exe_name):
        if p.is_file():
            if p.parent != dest_dir:
                shutil.copy2(p, direct)
            return direct
    # Any single .exe in tree
    exes = list(dest_dir.rglob("*.exe"))
    if len(exes) == 1:
        shutil.copy2(exes[0], direct)
        return direct
    return None


def _repair_tool(tool_id: str, spec: Dict[str, Any], log_fn: Optional[Callable]) -> bool:
    exe_name = spec.get("exe") or f"{tool_id}.exe"
    dest = get_bundled_exe_path(tool_id)
    if dest.is_file() and _verify_binary(dest):
        _log(f"bootstrap: {tool_id} bundled OK at {dest}", "info", log_fn)
        return True

    assets_dir = get_installer_assets_dir(tool_id)
    dest_dir = get_bundled_tool_dir(tool_id)
    dest_dir.mkdir(parents=True, exist_ok=True)

    candidates: List[Path] = []
    if assets_dir.is_dir():
        candidates.append(assets_dir / exe_name)
        zip_name = spec.get("zip") or f"{tool_id}_windows_amd64.zip"
        candidates.append(assets_dir / zip_name)
        versioned = sorted(assets_dir.glob(f"{tool_id}*_windows_amd64.zip"), reverse=True)
        for zp in versioned:
            candidates.append(zp)

    for src in candidates:
        if not src.is_file():
            continue
        _log(f"bootstrap: repairing {tool_id} from {src}", "info", log_fn)
        try:
            if src.suffix.lower() == ".zip":
                out = _extract_zip(src, dest_dir, exe_name)
                if out and _verify_binary(out):
                    _log(f"bootstrap: {tool_id} extracted to {out}", "success", log_fn)
                    return True
            else:
                shutil.copy2(src, dest)
                if _verify_binary(dest):
                    _log(f"bootstrap: {tool_id} copied to {dest}", "success", log_fn)
                    return True
        except Exception as e:
            _log(f"bootstrap: {tool_id} repair failed from {src}: {e}", "error", log_fn)

    resolved = resolve_tool_binary(tool_id)
    if resolved and resolved.source == "system":
        _log(
            f"bootstrap: {tool_id} not bundled (system fallback at {resolved.path} ignored for core bundle)",
            "warning",
            log_fn,
        )

    _log(f"bootstrap: {tool_id} missing — place {exe_name} in {dest_dir} or {assets_dir}", "warning", log_fn)
    return False


def bootstrap_guardian_core(
    force: bool = False,
    log_fn: Optional[Callable[[str, str], None]] = None,
    download_if_missing: bool = True,
) -> Dict[str, Any]:
    """
    Verify bundled Guardian core tools; repair from installer assets when possible.
    Downloads ProjectDiscovery releases when assets/tools are empty.
    """
    manifest = _load_manifest()
    tool_specs = {t["id"]: t for t in manifest.get("tools", []) if t.get("id") in CORE_TOOL_IDS}

    if download_if_missing:
        try:
            from workers.guardian.guardian_tool_fetcher import ensure_guardian_core_staged
            ensure_guardian_core_staged(log_fn=log_fn, force=force)
        except Exception as e:
            _log(f"bootstrap: auto-stage failed: {e}", "error", log_fn)

    _log("bootstrap: verifying Guardian core toolchain", "info", log_fn)
    results: Dict[str, Any] = {"tools": {}, "ok": True, "repaired": []}

    for tool_id in CORE_TOOL_IDS:
        spec = tool_specs.get(tool_id, {"id": tool_id, "exe": f"{tool_id}.exe"})
        ok = _repair_tool(tool_id, spec, log_fn)
        diag = diagnose_core_tool(tool_id)
        results["tools"][tool_id] = diag
        if not ok and not diag.get("installed"):
            results["ok"] = False
        elif ok and get_bundled_exe_path(tool_id).is_file():
            results["repaired"].append(tool_id)

    # Nuclei templates — first install / after repair only (can take minutes)
    had_state = _state_path().is_file()
    run_templates = not had_state or bool(results["repaired"])
    nuc = resolve_tool_binary("nuclei")
    if nuc and run_templates:
        try:
            subprocess.run(
                [nuc.path, "-update-templates", "-silent"],
                capture_output=True,
                timeout=180,
            )
            _log("bootstrap: nuclei templates update attempted", "info", log_fn)
        except Exception as e:
            _log(f"bootstrap: nuclei templates skipped: {e}", "warning", log_fn)

    state = {
        "last_run": datetime.now().isoformat(),
        "ok": results["ok"],
        "tools": {k: v.get("status_line") for k, v in results["tools"].items()},
        "force": force,
        "repaired": results["repaired"],
    }
    try:
        sp = _state_path()
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        _log(f"bootstrap: state save failed: {e}", "warning", log_fn)

    summary = ", ".join(f"{k}={v.get('status_line')}" for k, v in results["tools"].items())
    _log(f"bootstrap: complete — {summary}", "success" if results["ok"] else "warning", log_fn)

    try:
        from workers.guardian.guardian_tool_fetcher import verify_bundled_tools_log
        verify_bundled_tools_log(log_fn=log_fn)
    except Exception as e:
        _log(f"bootstrap: verification log failed: {e}", "warning", log_fn)

    return results


def should_run_bootstrap() -> bool:
    """Run on first launch or when any core bundled exe is missing."""
    sp = _state_path()
    if not sp.is_file():
        return True
    for tool_id in CORE_TOOL_IDS:
        dest = get_bundled_exe_path(tool_id)
        if not dest.is_file():
            return True
    return False
