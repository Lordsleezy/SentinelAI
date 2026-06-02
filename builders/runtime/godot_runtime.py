"""
Godot runtime — bundled-first resolution, install, and browse for GAME launches.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
logger = logging.getLogger("sentinel.builders.godot")

_CONFIG_REL = Path("memory") / "vault" / "builder_runtime.json"
_USER_PATHS = [
    r"C:\Tools\Godot.exe",
    r"C:\Program Files\Godot\Godot.exe",
    r"C:\Program Files (x86)\Godot\Godot.exe",
]


def get_sentinel_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def get_bundled_godot_dir() -> Path:
    return get_sentinel_root() / "tools" / "godot"


def get_installer_assets_godot_dir() -> Path:
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        p = Path(sys._MEIPASS) / "installer_assets" / "godot_runtime"
        if p.is_dir():
            return p
    return get_sentinel_root() / "installer_assets" / "godot_runtime"


def _config_path() -> Path:
    return get_sentinel_root() / _CONFIG_REL


def _load_config() -> Dict[str, Any]:
    p = _config_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_config(data: Dict[str, Any]) -> None:
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _is_valid_godot_exe(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != ".exe":
        return False
    try:
        proc = subprocess.run(
            [str(path), "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return "godot engine" in out.lower() or proc.returncode == 0
    except Exception:
        return path.stat().st_size > 5_000_000


def _glob_bundled_exes() -> list[Path]:
    d = get_bundled_godot_dir()
    if not d.is_dir():
        return []
    exes = list(d.rglob("Godot*.exe")) + list(d.rglob("godot*.exe"))
    return sorted({p.resolve() for p in exes if p.is_file()}, key=lambda p: p.name)


def iter_godot_candidates() -> List[Tuple[str, str]]:
    """(path, source) — bundled → configured → user → PATH."""
    seen: set[str] = set()
    out: List[Tuple[str, str]] = []

    def _add(p: Optional[str], source: str) -> None:
        if not p:
            return
        path = Path(p)
        if not path.is_file():
            return
        key = str(path.resolve())
        if key in seen:
            return
        if not _is_valid_godot_exe(path):
            return
        seen.add(key)
        out.append((key, source))

    for exe in _glob_bundled_exes():
        _add(str(exe), "bundled")

    cfg = _load_config().get("godot_path", "")
    _add(cfg, "configured")

    for raw in _USER_PATHS:
        _add(raw, "system")

    which = shutil.which("godot") or shutil.which("Godot") or shutil.which("godot.exe")
    _add(which, "system")

    return out


def find_godot() -> Optional[str]:
    cands = iter_godot_candidates()
    return cands[0][0] if cands else None


def is_godot_installed() -> bool:
    return find_godot() is not None


def godot_diagnostic() -> Dict[str, object]:
    cands = iter_godot_candidates()
    if not cands:
        return {
            "installed": False,
            "source": None,
            "path": None,
            "status_line": "✗ Godot Missing",
            "bundled": False,
        }
    path, source = cands[0]
    if source == "bundled":
        line = "✓ Godot Installed (Bundled)"
    else:
        line = "✓ Godot Installed"
    return {
        "installed": True,
        "source": source,
        "path": path,
        "status_line": line,
        "bundled": source == "bundled",
    }


def register_godot_path(exe_path: str, copy_to_bundle: bool = True) -> Dict[str, object]:
    path = Path(exe_path).expanduser().resolve()
    if not _is_valid_godot_exe(path):
        return {"ok": False, "error": "Not a valid Godot Engine executable"}

    dest = path
    if copy_to_bundle:
        bundle_dir = get_bundled_godot_dir()
        bundle_dir.mkdir(parents=True, exist_ok=True)
        dest = bundle_dir / path.name
        if dest.resolve() != path.resolve():
            shutil.copy2(path, dest)

    cfg = _load_config()
    cfg["godot_path"] = str(dest)
    _save_config(cfg)
    logger.info("[BUILDER] Godot registered at %s", dest)
    return {"ok": True, "path": str(dest), "diagnostic": godot_diagnostic()}


def browse_godot_exe() -> Dict[str, object]:
    """Open native file picker (Windows/desktop)."""
    if sys.platform != "win32":
        return {"ok": False, "error": "Browse is only supported on Windows desktop"}
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askopenfilename(
            title="Select Godot Engine",
            filetypes=[("Godot executable", "Godot*.exe"), ("Executable", "*.exe")],
        )
        root.destroy()
        if not chosen:
            return {"ok": False, "cancelled": True}
        return register_godot_path(chosen)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _download_godot_win64(dest_dir: Path, log: Optional[Callable[[str], None]] = None) -> Optional[Path]:
    """Download latest Godot 4.x win64 .exe from GitHub releases."""
    from urllib.request import urlretrieve
    import urllib.request
    try:
        with urllib.request.urlopen(
            "https://api.github.com/repos/godotengine/godot/releases/latest",
            timeout=30,
        ) as resp:
            release = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        if log:
            log(f"GitHub API failed: {e}")
        return None

    asset_url = None
    asset_name = None
    for a in release.get("assets", []):
        name = a.get("name", "")
        if re.search(r"win64.*\.zip$", name, re.I) or re.search(r"win64.*\.exe$", name, re.I):
            asset_url = a.get("browser_download_url")
            asset_name = name
            break
    if not asset_url or not asset_name:
        return None

    dest_dir.mkdir(parents=True, exist_ok=True)
    archive = dest_dir / asset_name
    if log:
        log(f"Downloading {asset_name}…")
    urlretrieve(asset_url, archive)

    if archive.suffix.lower() == ".zip":
        with zipfile.ZipFile(archive, "r") as zf:
            zf.extractall(dest_dir)
        archive.unlink(missing_ok=True)
        for exe in dest_dir.glob("Godot*.exe"):
            if _is_valid_godot_exe(exe):
                return exe
        return None

    if _is_valid_godot_exe(archive):
        return archive
    return None


def install_godot(log_fn: Optional[Callable[[str, str], None]] = None) -> Dict[str, object]:
    """
    Install Godot: bundled installer assets first, then GitHub download.
    """
    def _log(msg: str, level: str = "info") -> None:
        logger.info(msg)
        if log_fn:
            log_fn(msg if msg.startswith("[BUILDER]") else f"[BUILDER] {msg}", level)

    bundle_dir = get_bundled_godot_dir()
    bundle_dir.mkdir(parents=True, exist_ok=True)

    existing = _glob_bundled_exes()
    if existing and _is_valid_godot_exe(existing[0]):
        _log("Godot already bundled")
        return {"ok": True, "path": str(existing[0]), "method": "existing", "diagnostic": godot_diagnostic()}

    assets_dir = get_installer_assets_godot_dir()
    if assets_dir.is_dir():
        for pattern in ("*.zip", "Godot*.exe", "godot*.exe"):
            for src in assets_dir.glob(pattern):
                _log(f"Installing from asset {src.name}")
                try:
                    if src.suffix.lower() == ".zip":
                        with zipfile.ZipFile(src, "r") as zf:
                            zf.extractall(bundle_dir)
                    else:
                        shutil.copy2(src, bundle_dir / src.name)
                    for exe in _glob_bundled_exes():
                        if _is_valid_godot_exe(exe):
                            register_godot_path(str(exe), copy_to_bundle=False)
                            return {"ok": True, "path": str(exe), "method": "installer_asset"}
                except Exception as e:
                    _log(f"Asset install failed: {e}", "warning")

    _log("Downloading Godot from godotengine/godot releases…")
    exe = _download_godot_win64(bundle_dir, log=lambda m: _log(m))
    if exe and _is_valid_godot_exe(exe):
        register_godot_path(str(exe), copy_to_bundle=False)
        return {"ok": True, "path": str(exe), "method": "download", "diagnostic": godot_diagnostic()}

    return {
        "ok": False,
        "error": "Could not install Godot automatically. Use Browse to select Godot.exe.",
    }


def bootstrap_godot_runtime(log_fn: Optional[Callable[[str, str], None]] = None) -> Dict[str, object]:
    """Verify bundled Godot on startup; repair from assets if configured."""
    if is_godot_installed():
        if log_fn:
            d = godot_diagnostic()
            log_fn(f"[BUILDER] Godot runtime OK — {d.get('path', '')}", "info")
        return {"ok": True, "skipped": True, "diagnostic": godot_diagnostic()}
    assets = get_installer_assets_godot_dir()
    if assets.is_dir() and any(assets.iterdir()):
        return install_godot(log_fn=log_fn)
    return {"ok": False, "diagnostic": godot_diagnostic(), "message": "Godot not installed"}


def launch_dependency_error() -> Dict[str, object]:
    return {
        "dependency": "godot",
        "needs_install": True,
        "prompt_title": "Godot required. Install now?",
        "prompt_actions": ["install", "browse", "cancel"],
    }
