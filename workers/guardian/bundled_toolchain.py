"""
Guardian bundled toolchain — resolve ProjectDiscovery core tools.

Search priority:
  1. Sentinel bundled:  <sentinel_root>/tools/<tool>/<tool>.exe
  2. User-installed:  C:\\Tools\\<tool>.exe (and common paths)
  3. PATH (shutil.which)

Used by tool wrappers, httpx_compat, diagnostics, and bootstrap.
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

CORE_TOOL_IDS = (
    "httpx", "subfinder", "katana", "nuclei",
    "naabu", "dnsx", "ffuf", "assetfinder",
)

# User-installed locations (priority 2)
_USER_PATHS: Dict[str, List[str]] = {
    "httpx": [
        r"C:\Tools\httpx.exe",
        r"C:\Program Files\httpx\httpx.exe",
        r"C:\Users\pgg12\go\bin\httpx.exe",
    ],
    "subfinder": [r"C:\Tools\subfinder.exe"],
    "katana": [r"C:\Tools\katana.exe"],
    "nuclei": [r"C:\Tools\nuclei.exe"],
    "amass": [r"C:\Tools\amass.exe"],
    "naabu": [r"C:\Tools\naabu.exe"],
    "dnsx": [r"C:\Tools\dnsx.exe"],
    "ffuf": [r"C:\Tools\ffuf.exe"],
    "assetfinder": [r"C:\Tools\assetfinder.exe"],
    "gowitness": [r"C:\Tools\gowitness.exe"],
}


@dataclass
class ResolvedTool:
    tool_id: str
    path: str
    source: str  # bundled | system


def get_sentinel_root() -> Path:
    """Writable Sentinel install / repo root (next to backend exe when frozen)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # workers/guardian/bundled_toolchain.py -> repo root
    return Path(__file__).resolve().parents[2]


def get_bundled_tool_dir(tool_id: str) -> Path:
    return get_sentinel_root() / "tools" / tool_id


def get_bundled_exe_path(tool_id: str) -> Path:
    name = "httpx.exe" if tool_id == "httpx" else f"{tool_id}.exe"
    return get_bundled_tool_dir(tool_id) / name


def get_installer_assets_dir(tool_id: str) -> Path:
    """Read-only repair source shipped with the installer."""
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        p = Path(sys._MEIPASS) / "installer_assets" / "guardian_core" / tool_id
        if p.is_dir():
            return p
    return get_sentinel_root() / "installer_assets" / "guardian_core" / tool_id


def _exe_exists(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _path_is_bundled(path: str) -> bool:
    try:
        resolved = Path(path).resolve()
        tools_root = (get_sentinel_root() / "tools").resolve()
        return tools_root in resolved.parents or resolved.parent == tools_root
    except OSError:
        return False


def iter_candidate_paths(tool_id: str) -> List[tuple[str, str]]:
    """Yield (path, source) in priority order."""
    seen: set[str] = set()
    out: List[tuple[str, str]] = []

    def _add(p: Optional[str], source: str) -> None:
        if not p:
            return
        norm = str(Path(p).resolve()) if Path(p).exists() else p
        if norm in seen:
            return
        if not _exe_exists(Path(p)):
            return
        seen.add(norm)
        out.append((str(Path(p).resolve()), source))

    bundled = get_bundled_exe_path(tool_id)
    _add(str(bundled), "bundled")

    for raw in _USER_PATHS.get(tool_id, []):
        _add(raw, "system")

    for name in (f"{tool_id}.exe", tool_id):
        found = shutil.which(name)
        _add(found, "system")

    return out


def resolve_tool_binary(tool_id: str) -> Optional[ResolvedTool]:
    """First matching executable in priority order."""
    for path, source in iter_candidate_paths(tool_id):
        return ResolvedTool(tool_id=tool_id, path=path, source=source)
    return None


def probe_tool_version(path: Optional[str]) -> tuple[Optional[str], str]:
    """Return (version_string, health: ok|fail|unknown)."""
    if not path:
        return None, "unknown"
    import subprocess
    for flag in ("-version", "-v", "version", "--version"):
        try:
            proc = subprocess.run(
                [path, flag],
                capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace",
            )
            out = (proc.stdout or proc.stderr or "").strip()
            if out:
                import re
                for line in out.splitlines():
                    m = re.search(r"v?\d+\.\d+(?:\.\d+)*", line, re.I)
                    if m and "Version" in line or m:
                        if "Version" in line or len(line) < 80:
                            return m.group(0), "ok" if proc.returncode == 0 else "fail"
                first = out.split("\n")[0][:80]
                return first, "ok" if proc.returncode == 0 else "fail"
        except (subprocess.TimeoutExpired, OSError):
            continue
    try:
        if Path(path).is_file() and Path(path).stat().st_size > 50_000:
            return None, "ok"
    except OSError:
        pass
    return None, "unknown"


def diagnose_core_tool(tool_id: str) -> Dict[str, object]:
    """
    Status for Tool Status panel.

    status_line: ✓ Bundled | ✓ System | ✗ Missing
    """
    labels = {
        "httpx": "ProjectDiscovery httpx",
        "subfinder": "Subfinder",
        "katana": "Katana",
        "nuclei": "Nuclei",
        "naabu": "Naabu",
        "dnsx": "dnsx",
        "ffuf": "ffuf",
        "assetfinder": "assetfinder",
        "gowitness": "gowitness",
    }
    label = labels.get(tool_id, tool_id.title())
    bundled_path = get_bundled_exe_path(tool_id)
    bundled_ok = _exe_exists(bundled_path)

    resolved: Optional[ResolvedTool] = None
    if tool_id == "httpx":
        try:
            from workers.guardian.tools.httpx_compat import find_projectdiscovery_httpx
            pd = find_projectdiscovery_httpx(lambda *_a, **_k: None)
            if pd and pd.path:
                src = "bundled" if _path_is_bundled(pd.path) else "system"
                resolved = ResolvedTool(tool_id="httpx", path=pd.path, source=src)
        except Exception:
            pass
    else:
        resolved = resolve_tool_binary(tool_id)

    if resolved and resolved.source == "bundled":
        status_line = "✓ Bundled"
        installed = True
        source = "bundled"
        path = resolved.path
    elif resolved:
        status_line = "✓ System"
        installed = True
        source = "system"
        path = resolved.path
    else:
        status_line = "✗ Missing"
        installed = False
        source = None
        path = None

    version, health = probe_tool_version(path) if installed else (None, "unknown")

    return {
        "id": tool_id,
        "label": label,
        "installed": installed,
        "bundled": bundled_ok or (source == "bundled"),
        "system": source == "system",
        "source": source,
        "path": path,
        "version": version,
        "health": health if installed else "missing",
        "status_line": status_line,
        "bundled_path": str(bundled_path) if bundled_ok else None,
    }


def diagnose_optional_tool(
    tool_id: str,
    label: str,
    *,
    is_available: bool,
    path: Optional[str],
    source: Optional[str] = None,
) -> Dict[str, object]:
    """ZAP / Amass — not part of bundled core."""
    if is_available:
        if source == "bundled" or (path and _path_is_bundled(path)):
            status_line = "✓ Bundled"
            src = "bundled"
        else:
            status_line = "✓ System"
            src = "system"
    else:
        status_line = "✗ Missing"
        src = None
    return {
        "id": tool_id,
        "label": label,
        "installed": is_available,
        "bundled": src == "bundled",
        "system": src == "system",
        "source": src,
        "path": path,
        "status_line": status_line,
    }
