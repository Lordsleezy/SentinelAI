"""
Download and stage ProjectDiscovery Guardian Core binaries (Windows amd64).

Stages to installer_assets/guardian_core/<tool>/ and tools/<tool>/<tool>.exe
when zips or exes are missing.
"""
from __future__ import annotations

import json
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from workers.guardian.bundled_toolchain import (
    CORE_TOOL_IDS,
    get_bundled_exe_path,
    get_bundled_tool_dir,
    get_installer_assets_dir,
    get_sentinel_root,
)

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com/repos/projectdiscovery/{repo}/releases/latest"


def _log(msg: str, level: str = "info", log_fn: Optional[Callable[[str, str], None]] = None) -> None:
    text = msg if msg.startswith("[GUARDIAN]") else f"[GUARDIAN] {msg}"
    if log_fn:
        try:
            log_fn(text, level)
        except Exception:
            pass
    getattr(logger, level if level in ("info", "warning", "error", "debug") else "info")(text)


def _load_manifest() -> Dict[str, Any]:
    mf = get_sentinel_root() / "installer_assets" / "guardian_core" / "manifest.json"
    if mf.is_file():
        try:
            return json.loads(mf.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "tools": [
            {"id": t, "exe": f"{t}.exe", "zip": f"{t}_windows_amd64.zip"}
            for t in CORE_TOOL_IDS
        ],
    }


_GITHUB_REPO_MAP = {
    "ffuf": "ffuf/ffuf",
    "assetfinder": "tomnomnom/assetfinder",
    "gowitness": "sensepost/gowitness",
}


def _github_repo_for(tool_id: str, spec: Optional[Dict[str, Any]] = None) -> str:
    if spec and spec.get("github_repo"):
        gr = spec["github_repo"]
        return gr if "/" in gr else f"projectdiscovery/{gr}"
    mapped = _GITHUB_REPO_MAP.get(tool_id)
    if mapped:
        return mapped if "/" in mapped else f"projectdiscovery/{mapped}"
    return f"projectdiscovery/{tool_id}"


def _github_latest_windows_asset(repo: str, preferred_zip: str = "", tool_id: str = "") -> tuple[str, str]:
    """Return (download_url, asset_filename) for latest windows_amd64 zip."""
    import httpx
    # repo may be "org/name" or short name for projectdiscovery/*
    if "/" in repo:
        api_repo = repo
        url = f"https://api.github.com/repos/{api_repo}/releases/latest"
    else:
        api_repo = repo
        url = _GITHUB_API.format(repo=repo)
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "SentinelAI-Guardian/1.0"}
    token = __import__("os").environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = httpx.get(url, headers=headers, timeout=45, follow_redirects=True)
    r.raise_for_status()
    data = r.json()
    assets = data.get("assets") or []
    if preferred_zip:
        for asset in assets:
            if asset.get("name") == preferred_zip:
                dl = asset.get("browser_download_url")
                if dl:
                    return dl, preferred_zip
    # Versioned names: httpx_1.9.0_windows_amd64.zip
    short = tool_id or (repo.split("/")[-1] if "/" in repo else repo)
    prefix = f"{short}_"
    for asset in assets:
        name = asset.get("name") or ""
        if name.endswith("_windows_amd64.zip") and name.lower().startswith(prefix):
            dl = asset.get("browser_download_url")
            if dl:
                return dl, name
    # Legacy: subfinder_windows_amd64.zip
    legacy = f"{repo}_windows_amd64.zip"
    for asset in assets:
        if asset.get("name") == legacy:
            dl = asset.get("browser_download_url")
            if dl:
                return dl, legacy
    names = [a.get("name") for a in assets if "windows" in (a.get("name") or "").lower()]
    raise RuntimeError(
        f"No windows_amd64 zip in projectdiscovery/{repo} latest release (assets: {names[:8]})"
    )


def _download_file(url: str, dest: Path, log_fn: Optional[Callable]) -> None:
    import httpx
    dest.parent.mkdir(parents=True, exist_ok=True)
    _log(f"Downloading {dest.name} …", "info", log_fn)
    with httpx.stream("GET", url, follow_redirects=True, timeout=300) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=65536):
                f.write(chunk)


def _extract_exe(zip_path: Path, dest_dir: Path, exe_name: str) -> Optional[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)
    direct = dest_dir / exe_name
    if direct.is_file():
        return direct
    for p in dest_dir.rglob(exe_name):
        if p.is_file():
            shutil.copy2(p, direct)
            return direct
    exes = list(dest_dir.rglob("*.exe"))
    if len(exes) == 1:
        shutil.copy2(exes[0], direct)
        return direct
    return None


def _find_staged_zip(assets_dir: Path, tool_id: str) -> Optional[Path]:
    if not assets_dir.is_dir():
        return None
    zips = sorted(assets_dir.glob(f"{tool_id}*_windows_amd64.zip"), reverse=True)
    if zips:
        return zips[0]
    legacy = assets_dir / f"{tool_id}_windows_amd64.zip"
    return legacy if legacy.is_file() else None


def _assets_need_download(tool_id: str, spec: Dict[str, Any]) -> bool:
    assets = get_installer_assets_dir(tool_id)
    exe_name = spec.get("exe") or f"{tool_id}.exe"
    if (assets / exe_name).is_file():
        return False
    if _find_staged_zip(assets, tool_id):
        return False
    return True


def stage_tool_from_github(
    tool_id: str,
    spec: Optional[Dict[str, Any]] = None,
    log_fn: Optional[Callable[[str, str], None]] = None,
) -> bool:
    """Download zip to installer_assets and install exe under tools/."""
    spec = spec or {"id": tool_id, "exe": f"{tool_id}.exe", "zip": f"{tool_id}_windows_amd64.zip"}
    exe_name = spec.get("exe") or f"{tool_id}.exe"
    zip_name = spec.get("zip") or f"{tool_id}_windows_amd64.zip"

    bundled = get_bundled_exe_path(tool_id)
    if bundled.is_file() and bundled.stat().st_size > 50_000:
        _log(f"{tool_id}: already bundled at {bundled}", "info", log_fn)
        return True

    assets_dir = get_installer_assets_dir(tool_id)
    assets_dir.mkdir(parents=True, exist_ok=True)
    tool_dir = get_bundled_tool_dir(tool_id)
    tool_dir.mkdir(parents=True, exist_ok=True)

    zip_path = _find_staged_zip(assets_dir, tool_id)
    if zip_path is None:
        zip_path = assets_dir / zip_name
    exe_in_assets = assets_dir / exe_name

    if not zip_path.is_file() and not exe_in_assets.is_file():
        try:
            gh_repo = _github_repo_for(tool_id, spec)
            url, asset_name = _github_latest_windows_asset(gh_repo, zip_name, tool_id)
            zip_path = assets_dir / asset_name
            _download_file(url, zip_path, log_fn)
        except Exception as e:
            _log(f"{tool_id}: download failed — {e}", "error", log_fn)
            return False

    try:
        if zip_path.is_file():
            out = _extract_exe(zip_path, tool_dir, exe_name)
            if out and out.is_file():
                shutil.copy2(out, exe_in_assets)
                _log(f"{tool_id}: staged to {out}", "success", log_fn)
                return True
        if exe_in_assets.is_file():
            shutil.copy2(exe_in_assets, bundled)
            _log(f"{tool_id}: copied to {bundled}", "success", log_fn)
            return bundled.is_file()
    except Exception as e:
        _log(f"{tool_id}: extract failed — {e}", "error", log_fn)
    return bundled.is_file() and bundled.stat().st_size > 50_000


def ensure_guardian_core_staged(
    log_fn: Optional[Callable[[str, str], None]] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Ensure installer_assets and tools/ contain all core binaries.
    Downloads from GitHub when missing.
    """
    manifest = _load_manifest()
    specs = {t["id"]: t for t in manifest.get("tools", []) if t.get("id") in CORE_TOOL_IDS}
    all_ids = list(CORE_TOOL_IDS)
    results: Dict[str, bool] = {}

    need_any = force or any(
        _assets_need_download(tid, specs.get(tid, {})) or not get_bundled_exe_path(tid).is_file()
        for tid in CORE_TOOL_IDS
    )
    if not need_any:
        _log("Guardian core assets present — skip download", "info", log_fn)
        return {"ok": True, "downloaded": [], "skipped": list(all_ids)}

    _log("Staging Guardian core tools from GitHub releases", "info", log_fn)
    for tool_id in all_ids:
        if force or _assets_need_download(tool_id, specs.get(tool_id, {})) or not get_bundled_exe_path(tool_id).is_file():
            results[tool_id] = stage_tool_from_github(tool_id, specs.get(tool_id), log_fn)
        else:
            results[tool_id] = True

    ok = all(results.get(t, False) for t in all_ids)
    return {"ok": ok, "tools": results}


def verify_bundled_tools_log(log_fn: Optional[Callable[[str, str], None]] = None) -> Dict[str, Any]:
    """Emit startup verification block; return per-tool status."""
    from workers.guardian.bundled_toolchain import diagnose_core_tool

    lines: List[str] = []
    all_bundled = True
    tools: Dict[str, Any] = {}

    for tool_id in CORE_TOOL_IDS:
        diag = diagnose_core_tool(tool_id)
        tools[tool_id] = diag
        bundled_ok = bool(diag.get("bundled")) and diag.get("status_line") == "✓ Bundled"
        mark = "✓" if bundled_ok else "✗"
        if not bundled_ok:
            all_bundled = False
        lines.append(f"{tool_id} {mark}")

    _log("Bundled tools verified", "success" if all_bundled else "warning", log_fn)
    for line in lines:
        _log(line, "success" if "✓" in line else "error", log_fn)

    return {"ok": all_bundled, "tools": tools, "lines": lines}
