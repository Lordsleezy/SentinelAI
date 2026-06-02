"""
Guardian Bootstrap Manager — auto-provision all required tools on first launch.

1. Check required tools
2. Download missing (GitHub / staging)
3. Verify hashes when manifest provides sha256
4. Extract & register paths
5. Install templates (nuclei)
6. Refresh tool registry + notify UI
"""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from workers.guardian.bundled_toolchain import get_bundled_exe_path, get_sentinel_root
from workers.guardian.guardian_tool_registry_store import (
    CORE_TOOL_NAMES,
    EXTENDED_TOOL_NAMES,
    refresh_registry,
    update_tool_record,
)

logger = logging.getLogger(__name__)

_ALL_TOOLS = list(CORE_TOOL_NAMES) + list(EXTENDED_TOOL_NAMES)
_STATE_REL = Path("memory") / "vault" / "guardian_bootstrap_state.json"


def _emit_progress(event: str, payload: Dict[str, Any]) -> None:
    try:
        from desktop_app import socketio
        if socketio:
            socketio.emit(event, payload)
    except Exception:
        pass


def _log(msg: str, level: str = "info", log_fn: Optional[Callable[[str, str], None]] = None) -> None:
    text = msg if msg.startswith("[GUARDIAN]") else f"[GUARDIAN] {msg}"
    logger.info(text) if level in ("info", "success") else logger.warning(text)
    if log_fn:
        try:
            log_fn(text, level)
        except Exception:
            pass
    _emit_progress("guardian_bootstrap_update", {"message": text, "level": level})


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_hash(path: Path, expected: Optional[str]) -> bool:
    if not expected or not path.is_file():
        return True
    try:
        return _sha256_file(path).lower() == expected.lower()
    except Exception:
        return False


def _load_manifest_tools() -> Dict[str, Dict[str, Any]]:
    mf = get_sentinel_root() / "installer_assets" / "guardian_core" / "manifest.json"
    if mf.is_file():
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
            return {t["id"]: t for t in data.get("tools", []) if t.get("id")}
        except Exception:
            pass
    return {}


def _install_nuclei_templates(log_fn: Optional[Callable]) -> None:
    from workers.guardian.bundled_toolchain import resolve_tool_binary
    nuc = resolve_tool_binary("nuclei")
    if not nuc:
        return
    try:
        subprocess.run(
            [nuc.path, "-update-templates", "-silent"],
            capture_output=True,
            timeout=300,
        )
        _log("Nuclei templates updated", "success", log_fn)
    except Exception as e:
        _log(f"Nuclei templates skipped: {e}", "warning", log_fn)


def _bootstrap_zap_note(log_fn: Optional[Callable]) -> None:
    """ZAP is external daemon — document install path, never show bare Missing without hint."""
    try:
        from workers.guardian.tools.zap_tool import ZAPTool
        z = ZAPTool(None)
        if z.is_available():
            update_tool_record("zap", install_status="installed", install_path=z.base, health="ok")
            _log("ZAP daemon reachable on :8090", "success", log_fn)
        else:
            update_tool_record(
                "zap",
                install_status="optional",
                health="missing",
                install_path="Install OWASP ZAP and start daemon (port 8090)",
            )
            _log("ZAP not running — optional; start ZAP for passive scan", "warning", log_fn)
    except Exception as e:
        _log(f"ZAP check: {e}", "warning", log_fn)


def run_bootstrap(
    *,
    force: bool = False,
    download: bool = True,
    log_fn: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, Any]:
    """
    Full bootstrap — ensures core tools are installed; best-effort extended tools.
    """
    _log("Bootstrap Manager: starting provisioning", "info", log_fn)
    manifest = _load_manifest_tools()
    results: Dict[str, bool] = {}

    if download:
        try:
            from workers.guardian.guardian_tool_fetcher import ensure_guardian_core_staged, stage_tool_from_github
            ensure_guardian_core_staged(log_fn=log_fn, force=force)
            for tool_id in EXTENDED_TOOL_NAMES:
                if tool_id == "zap":
                    continue
                spec = manifest.get(tool_id, {"id": tool_id})
                dest = get_bundled_exe_path(tool_id)
                if force or not dest.is_file():
                    _log(f"Staging extended tool: {tool_id}", "info", log_fn)
                    results[tool_id] = stage_tool_from_github(tool_id, spec, log_fn)
        except Exception as e:
            _log(f"Download phase error: {e}", "error", log_fn)

    try:
        from workers.guardian.guardian_bootstrap import bootstrap_guardian_core
        core_res = bootstrap_guardian_core(
            force=force,
            download_if_missing=download,
            log_fn=log_fn,
        )
        results["core_bundle"] = core_res.get("ok", False)
    except Exception as e:
        _log(f"Core bootstrap error: {e}", "error", log_fn)
        results["core_bundle"] = False

    _install_nuclei_templates(log_fn)
    _bootstrap_zap_note(log_fn)

    registry = refresh_registry()
    tools = registry.get("tools", {})
    missing_core = [t for t in CORE_TOOL_NAMES if tools.get(t, {}).get("install_status") != "installed"]
    missing_ext = [
        t for t in EXTENDED_TOOL_NAMES
        if tools.get(t, {}).get("install_status") not in ("installed", "optional")
    ]

    state = {
        "last_run": datetime.now().isoformat(),
        "force": force,
        "missing_core": missing_core,
        "missing_extended": missing_ext,
        "core_ready": not missing_core,
    }
    try:
        sp = get_sentinel_root() / _STATE_REL
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass

    _emit_progress("guardian_bootstrap_complete", {
        "registry": registry,
        "missing_core": missing_core,
        "missing_extended": missing_ext,
        "ok": not missing_core,
    })
    _log(
        f"Bootstrap complete — core missing: {missing_core or 'none'}; extended: {missing_ext or 'none'}",
        "success" if not missing_core else "warning",
        log_fn,
    )
    return {
        "ok": not missing_core,
        "registry": registry,
        "results": results,
        "missing_core": missing_core,
        "missing_extended": missing_ext,
    }


def should_run_bootstrap() -> bool:
    from workers.guardian.guardian_bootstrap import should_run_bootstrap as _legacy
    if _legacy():
        return True
    reg = refresh_registry()
    tools = reg.get("tools") or {}
    for tid in CORE_TOOL_NAMES:
        if tools.get(tid, {}).get("install_status") != "installed":
            return True
    return False
