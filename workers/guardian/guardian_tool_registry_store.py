"""
Persistent Guardian Tool Registry — name, version, path, status, last verified.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from workers.guardian.bundled_toolchain import diagnose_core_tool, get_sentinel_root, probe_tool_version, resolve_tool_binary

logger = logging.getLogger(__name__)

_REGISTRY_PATH = Path("memory") / "vault" / "guardian_tool_registry.json"

CORE_TOOL_NAMES = ("httpx", "subfinder", "katana", "nuclei", "dnsx", "naabu")
EXTENDED_TOOL_NAMES = ("amass", "assetfinder", "ffuf", "gowitness", "zap")


def _registry_file() -> Path:
    p = get_sentinel_root() / _REGISTRY_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_registry() -> Dict[str, Any]:
    path = _registry_file()
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("tool registry load failed: %s", e)
    return {"tools": {}, "last_bootstrap": None, "version": 1}


def save_registry(data: Dict[str, Any]) -> None:
    _registry_file().write_text(json.dumps(data, indent=2), encoding="utf-8")


def _probe_tool(tool_id: str) -> Dict[str, Any]:
    if tool_id == "zap":
        try:
            from workers.guardian.tools.zap_tool import ZAPTool
            z = ZAPTool(None)
            ok = z.is_available()
            return {
                "name": tool_id,
                "version": "daemon" if ok else None,
                "install_path": f"{z.base}" if ok else None,
                "install_status": "installed" if ok else "missing",
                "health": "ok" if ok else "missing",
                "last_verified": datetime.now().isoformat(),
                "category": "extended",
            }
        except Exception:
            pass
    if tool_id == "amass":
        try:
            from workers.guardian.tools.amass_tool import AmassTool
            a = AmassTool(None)
            path = getattr(a, "_get_bin", lambda: None)()
            ok = a.is_available()
            ver, health = probe_tool_version(path) if path else (None, "missing")
            return {
                "name": tool_id,
                "version": ver,
                "install_path": path,
                "install_status": "installed" if ok else "missing",
                "health": health if ok else "missing",
                "last_verified": datetime.now().isoformat(),
                "category": "extended",
            }
        except Exception:
            pass

    if tool_id in CORE_TOOL_NAMES:
        diag = diagnose_core_tool(tool_id)
        installed = bool(diag.get("installed"))
        return {
            "name": tool_id,
            "version": diag.get("version"),
            "install_path": diag.get("path"),
            "install_status": "installed" if installed else "missing",
            "health": diag.get("health", "unknown"),
            "last_verified": datetime.now().isoformat(),
            "category": "core",
            "status_line": diag.get("status_line"),
        }

    resolved = resolve_tool_binary(tool_id)
    path = resolved.path if resolved else None
    ver, health = probe_tool_version(path) if path else (None, "missing")
    installed = bool(path)
    return {
        "name": tool_id,
        "version": ver,
        "install_path": path,
        "install_status": "installed" if installed else "missing",
        "health": health,
        "last_verified": datetime.now().isoformat(),
        "category": "extended",
    }


def refresh_registry() -> Dict[str, Any]:
    data = load_registry()
    tools: Dict[str, Any] = {}
    for tid in list(CORE_TOOL_NAMES) + list(EXTENDED_TOOL_NAMES):
        tools[tid] = _probe_tool(tid)
    data["tools"] = tools
    data["updated_at"] = datetime.now().isoformat()
    core_ok = all(tools[t]["install_status"] == "installed" for t in CORE_TOOL_NAMES)
    data["core_ready"] = core_ok
    save_registry(data)
    return data


def get_registry_list() -> List[Dict[str, Any]]:
    data = load_registry()
    tools = data.get("tools") or {}
    if not tools:
        data = refresh_registry()
        tools = data.get("tools") or {}
    return list(tools.values())


def update_tool_record(tool_id: str, **fields: Any) -> None:
    data = load_registry()
    rec = data.setdefault("tools", {}).setdefault(tool_id, {"name": tool_id})
    rec.update(fields)
    rec["last_verified"] = datetime.now().isoformat()
    save_registry(data)
