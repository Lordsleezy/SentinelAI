"""Desktop operator — OS-level automation (Windows-first)."""
from __future__ import annotations

import logging
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sentinel.vision.desktop")


class DesktopOperator:
    def __init__(self) -> None:
        self._system = platform.system().lower()

    @property
    def platform(self) -> str:
        return self._system

    def launch_app(self, command: List[str], *, cwd: Optional[str] = None) -> Dict[str, Any]:
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=(self._system == "windows" and len(command) == 1),
        )
        return {"ok": True, "pid": proc.pid, "command": command}

    def close_app(self, pid: int) -> Dict[str, Any]:
        if self._system == "windows":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False, capture_output=True)
        else:
            subprocess.run(["kill", str(pid)], check=False, capture_output=True)
        return {"ok": True, "pid": pid}

    def open_terminal(self, command: str, *, cwd: Optional[str] = None) -> Dict[str, Any]:
        return self.run_command(command, cwd=cwd)

    def run_command(self, command: str, *, cwd: Optional[str] = None, timeout: int = 300) -> Dict[str, Any]:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd or str(Path(__file__).resolve().parents[4]),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": (result.stdout or "")[-8000:],
            "stderr": (result.stderr or "")[-4000:],
        }

    def manage_files(self, action: str, path: str, dest: Optional[str] = None) -> Dict[str, Any]:
        p = Path(path)
        if action == "read" and p.is_file():
            return {"ok": True, "content": p.read_text(encoding="utf-8", errors="replace")[:20000]}
        if action == "exists":
            return {"ok": True, "exists": p.exists()}
        if action == "mkdir":
            p.mkdir(parents=True, exist_ok=True)
            return {"ok": True}
        if action == "copy" and dest:
            import shutil
            shutil.copy2(path, dest)
            return {"ok": True, "dest": dest}
        return {"ok": False, "error": f"unsupported file action: {action}"}

    def type_text(self, text: str) -> Dict[str, Any]:
        try:
            import pyautogui
            pyautogui.write(text, interval=0.02)
            return {"ok": True}
        except ImportError:
            return {"ok": False, "error": "pyautogui not installed — pip install pyautogui for desktop typing"}

    def click_screen(self, x: int, y: int) -> Dict[str, Any]:
        try:
            import pyautogui
            pyautogui.click(x, y)
            return {"ok": True}
        except ImportError:
            return {"ok": False, "error": "pyautogui not installed"}

    def move_mouse(self, x: int, y: int) -> Dict[str, Any]:
        try:
            import pyautogui
            pyautogui.moveTo(x, y)
            return {"ok": True}
        except ImportError:
            return {"ok": False, "error": "pyautogui not installed"}

    def read_window(self) -> Dict[str, Any]:
        if self._system != "windows":
            return {"ok": False, "error": "read_window only implemented on Windows"}
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            return {"ok": True, "title": buf.value, "hwnd": hwnd}
        except Exception as e:
            return {"ok": False, "error": str(e)}
