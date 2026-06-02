"""Desktop Builder — Electron-first (Tauri/Python fallback)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, List, Optional

from builders.common.logging_util import log_builder
from builders.common.types import BuildResult


class DesktopBuilder:
    name = "Electron"
    project_type = "DESKTOP"

    def __init__(self, socketio: Any = None):
        self.socketio = socketio

    def build(self, description: str, output_dir: Optional[str] = None) -> BuildResult:
        log_builder(f"Desktop/Electron build: {description[:80]}", "info", self.socketio)
        out = self._resolve_output(description, output_dir)
        out.mkdir(parents=True, exist_ok=True)
        files: List[str] = []

        is_calc = "calculator" in description.lower()
        title = "Calculator" if is_calc else "Sentinel App"

        pkg = {
            "name": re.sub(r"[^a-z0-9-]", "-", title.lower())[:32],
            "version": "1.0.0",
            "main": "main.js",
            "scripts": {"start": "electron ."},
            "devDependencies": {"electron": "^28.0.0"},
        }
        files.append(self._write(out / "package.json", json.dumps(pkg, indent=2)))
        files.append(self._write(out / "main.js", _MAIN_JS))
        files.append(self._write(out / "index.html", _CALC_HTML if is_calc else _GENERIC_HTML.format(title=title)))
        files.append(self._write(out / "preload.js", "// Sentinel preload\n"))

        launch = f'cd /d "{out}" && npm install && npm start'
        return BuildResult(
            success=True,
            builder=self.name,
            project_type=self.project_type,
            output_dir=str(out),
            entry_point=str(out / "main.js"),
            launch_command=launch,
            files=files,
            build_logs="Electron desktop scaffold created. Run npm install && npm start.",
            artifact_type="app",
        )

    def _resolve_output(self, description: str, output_dir: Optional[str]) -> Path:
        if output_dir:
            return Path(output_dir).expanduser().resolve()
        name = "calculator" if "calculator" in description.lower() else "sentinel_desktop"
        return Path.home() / "Desktop" / name

    def _write(self, path: Path, content: str) -> str:
        path.write_text(content, encoding="utf-8")
        return str(path)


_MAIN_JS = """\
const { app, BrowserWindow } = require('electron');
const path = require('path');

function createWindow() {
  const win = new BrowserWindow({
    width: 400,
    height: 520,
    webPreferences: { preload: path.join(__dirname, 'preload.js') },
  });
  win.loadFile('index.html');
}

app.whenReady().then(createWindow);
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
"""

_CALC_HTML = """\
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Calculator</title>
  <style>
    body { font-family: system-ui; background: #1a1a2e; color: #eee; margin: 0; padding: 16px; }
    #display { width: 100%; font-size: 2rem; padding: 12px; box-sizing: border-box; margin-bottom: 12px; }
    .grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
    button { padding: 18px; font-size: 1.2rem; border: none; border-radius: 8px; cursor: pointer; background: #16213e; color: #fff; }
    button.op { background: #0f3460; }
    button.eq { background: #e94560; }
  </style>
</head>
<body>
  <input id="display" readonly value="0">
  <div class="grid" id="keys"></div>
  <script>
    const d = document.getElementById('display');
    let cur = '0';
    const keys = ['7','8','9','/','4','5','6','*','1','2','3','-','0','.','=','+','C'];
    const grid = document.getElementById('keys');
    keys.forEach(k => {
      const b = document.createElement('button');
      b.textContent = k;
      b.className = k === '=' ? 'eq' : 'op';
      b.onclick = () => {
        if (k === 'C') { cur = '0'; d.value = cur; return; }
        if (k === '=') { try { cur = String(eval(cur)); } catch { cur = 'Error'; } d.value = cur; return; }
        cur = cur === '0' ? k : cur + k;
        d.value = cur;
      };
      grid.appendChild(b);
    });
  </script>
</body>
</html>
"""

_GENERIC_HTML = """\
<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>{title}</title></head>
<body><h1>{title}</h1><p>Built by Sentinel Desktop Builder.</p></body></html>
"""
