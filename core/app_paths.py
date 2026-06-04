"""
Writable vs install paths for SentinelAI.

Packaged installs live under Program Files (read-only). All user writes
(.env, config, SQLite) go to %APPDATA%\\SentinelAI (Electron userData).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def is_packaged_runtime() -> bool:
    """True when running from PyInstaller bundle (onedir or onefile)."""
    if getattr(sys, "frozen", False):
        return True
    if getattr(sys, "_MEIPASS", None):
        return True
    exe = (getattr(sys, "executable", "") or "").lower()
    return exe.endswith("sentinel_backend.exe")


def bootstrap_packaged_env() -> None:
    """Ensure writable AppData paths before any module caches data locations."""
    if not is_packaged_runtime():
        return
    root = resolve_user_data_dir()
    os.environ.setdefault("SENTINELAI_USER_DATA", str(root))
    os.environ.setdefault("SENTINELAI_ENV_PATH", str(root / ".env"))
    os.environ.setdefault("SENTINELAI_DATA_DIR", str(root / "data"))


def resolve_user_data_dir() -> Path:
    """Per-user writable root (matches Electron app.getPath('userData'))."""
    for key in ("SENTINELAI_USER_DATA",):
        raw = os.environ.get(key, "").strip()
        if raw:
            return Path(raw)
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "").strip()
        if appdata:
            return Path(appdata) / "SentinelAI"
    return Path.home() / ".sentinelai"


def resolve_env_path() -> Path:
    raw = os.environ.get("SENTINELAI_ENV_PATH", "").strip()
    if raw:
        return Path(raw)
    return resolve_user_data_dir() / ".env"


def resolve_env_example_path() -> Path | None:
    """Bundled or dev template — read-only seed for first-run copy."""
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        bundled = Path(sys._MEIPASS) / ".env.example"
        if bundled.is_file():
            return bundled
    repo = Path(__file__).resolve().parents[1]
    for candidate in (repo / ".env.example", repo / "resources" / ".env.example"):
        if candidate.is_file():
            return candidate
    return None


def resolve_data_dir() -> Path:
    raw = os.environ.get("SENTINELAI_DATA_DIR", "").strip()
    if raw:
        return Path(raw)
    if is_packaged_runtime():
        return resolve_user_data_dir() / "data"
    return Path(__file__).resolve().parents[1] / "data"


def resolve_data_path(*parts: str) -> Path:
    """Writable path under per-user data (never Program Files)."""
    return resolve_data_dir().joinpath(*parts)


def resolve_config_dir() -> Path:
    return resolve_user_data_dir() / "config"


def ensure_user_data_dirs() -> Path:
    root = resolve_user_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    resolve_data_dir().mkdir(parents=True, exist_ok=True)
    resolve_config_dir().mkdir(parents=True, exist_ok=True)
    return root


def load_sentinel_env() -> Path:
    """Load user .env from AppData (or dev project root fallback)."""
    ensure_user_data_dirs()
    env_path = resolve_env_path()
    if not env_path.is_file() and not getattr(sys, "frozen", False):
        dev_env = Path(__file__).resolve().parents[1] / ".env"
        if dev_env.is_file():
            env_path = dev_env
    try:
        from dotenv import load_dotenv

        if env_path.is_file():
            load_dotenv(env_path, override=False)
    except ImportError:
        pass
    return env_path
