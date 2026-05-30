"""openclaw/mcp_tools.py — Personal-assistant capabilities for SentinelAI.

These give Sentinel real-world reach beyond coding: computer control, file
management, system info and quick web tasks.

Safety model (enforced by openclaw.receive_message intent routing):
  * READ-ONLY / REVERSIBLE actions (open_app, screenshot, clipboard read,
    list/read files, system info, web search, open_url) run directly.
  * IRREVERSIBLE actions (write_file, delete) must go through the approval gate.

Every function degrades gracefully — optional deps (pyautogui, PIL) are probed
at call time and missing-dependency errors are returned, never raised.
"""
from __future__ import annotations

import base64
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

# pyperclip is bundled with pyautogui; we still probe defensively.


def _ok(data) -> Dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg) -> Dict:
    return {"ok": False, "data": None, "error": str(msg)}


def _have(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:
        return False


# ─── COMPUTER CONTROL ─────────────────────────────────────────────────────────

def open_app(app_name: str) -> Dict:
    """Open an application by name. Cross-platform best effort."""
    if not app_name:
        return _err("app_name required")
    try:
        if sys.platform.startswith("win"):
            # `start` is a shell builtin; use cmd.
            subprocess.Popen(["cmd", "/c", "start", "", app_name], shell=False)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-a", app_name])
        else:
            subprocess.Popen([app_name])
        return _ok({"opened": app_name})
    except Exception as exc:
        return _err(exc)


def take_screenshot() -> Dict:
    """Return a base64-encoded PNG of the primary screen."""
    if not _have("PIL"):
        return _err("Pillow not installed")
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return _ok({"image_base64": b64, "format": "png", "size": img.size})
    except Exception as exc:
        return _err(exc)


def get_clipboard() -> Dict:
    try:
        if _have("pyperclip"):
            import pyperclip
            return _ok({"text": pyperclip.paste()})
        if _have("pyautogui"):
            import pyautogui  # noqa
        return _err("clipboard backend unavailable (install pyperclip)")
    except Exception as exc:
        return _err(exc)


def set_clipboard(text: str) -> Dict:
    try:
        if _have("pyperclip"):
            import pyperclip
            pyperclip.copy(text or "")
            return _ok({"set": True})
        return _err("clipboard backend unavailable (install pyperclip)")
    except Exception as exc:
        return _err(exc)


def type_text(text: str) -> Dict:
    """Type text at the current cursor via pyautogui."""
    if not _have("pyautogui"):
        return _err("pyautogui not installed")
    try:
        import pyautogui
        pyautogui.typewrite(text or "", interval=0.01)
        return _ok({"typed_chars": len(text or "")})
    except Exception as exc:
        return _err(exc)


# ─── FILE MANAGEMENT ──────────────────────────────────────────────────────────

def list_directory(path: str) -> Dict:
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return _err(f"not found: {path}")
        entries = [{"name": e.name, "is_dir": e.is_dir(),
                    "size": (e.stat().st_size if e.is_file() else None)}
                   for e in sorted(p.iterdir())]
        return _ok({"path": str(p), "entries": entries})
    except Exception as exc:
        return _err(exc)


def read_file(path: str, max_bytes: int = 200_000) -> Dict:
    try:
        p = Path(path).expanduser()
        if not p.is_file():
            return _err(f"not a file: {path}")
        data = p.read_text(encoding="utf-8", errors="replace")[:max_bytes]
        return _ok({"path": str(p), "content": data})
    except Exception as exc:
        return _err(exc)


def write_file(path: str, content: str) -> Dict:
    """IRREVERSIBLE — callers must gate this behind approval."""
    try:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content or "", encoding="utf-8")
        return _ok({"path": str(p), "bytes": len(content or "")})
    except Exception as exc:
        return _err(exc)


def search_files(query: str, directory: str = ".") -> Dict:
    try:
        root = Path(directory).expanduser()
        matches: List[str] = []
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                if query.lower() in f.lower():
                    matches.append(os.path.join(dirpath, f))
                    if len(matches) >= 200:
                        return _ok({"matches": matches, "truncated": True})
        return _ok({"matches": matches, "truncated": False})
    except Exception as exc:
        return _err(exc)


# ─── SYSTEM INFO ──────────────────────────────────────────────────────────────

def get_running_processes() -> Dict:
    if not _have("psutil"):
        return _err("psutil not installed")
    try:
        import psutil
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent"]):
            procs.append(p.info)
            if len(procs) >= 300:
                break
        return _ok({"processes": procs})
    except Exception as exc:
        return _err(exc)


def get_disk_usage() -> Dict:
    try:
        usage = shutil.disk_usage(os.path.expanduser("~"))
        return _ok({"total": usage.total, "used": usage.used, "free": usage.free,
                    "percent": round(usage.used / usage.total * 100, 1)})
    except Exception as exc:
        return _err(exc)


def get_network_status() -> Dict:
    try:
        import socket
        host = socket.gethostname()
        try:
            ip = socket.gethostbyname(host)
        except Exception:
            ip = "unknown"
        online = False
        try:
            socket.create_connection(("1.1.1.1", 53), timeout=2).close()
            online = True
        except Exception:
            online = False
        return _ok({"hostname": host, "ip": ip, "online": online})
    except Exception as exc:
        return _err(exc)


# ─── WEB TASKS ────────────────────────────────────────────────────────────────

def open_url(url: str) -> Dict:
    try:
        import webbrowser
        webbrowser.open(url)
        return _ok({"opened": url})
    except Exception as exc:
        return _err(exc)


def web_search_quick(query: str) -> Dict:
    """Top 3 results via the existing web_worker (no browser)."""
    try:
        from workers import web_worker
        res = web_worker.run_web_task("mcp-search", query)
        data = res.get("data") if isinstance(res, dict) else res
        results = []
        if isinstance(data, dict):
            results = data.get("results") or data.get("items") or []
        return _ok({"query": query, "results": results[:3]})
    except Exception as exc:
        return _err(exc)


def capabilities() -> Dict:
    """Report which MCP capabilities are usable in this environment."""
    return {
        "pyautogui": _have("pyautogui"),
        "pillow": _have("PIL"),
        "pyperclip": _have("pyperclip"),
        "psutil": _have("psutil"),
        "platform": sys.platform,
    }
