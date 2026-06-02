"""Web Builder — Next.js + React + Tailwind scaffold."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, List, Optional

from builders.common.logging_util import log_builder
from builders.common.types import BuildResult


class WebBuilder:
    name = "Next.js"
    project_type = "WEB"

    def __init__(self, socketio: Any = None):
        self.socketio = socketio

    def build(self, description: str, output_dir: Optional[str] = None) -> BuildResult:
        log_builder(f"Web/Next.js build: {description[:80]}", "info", self.socketio)
        out = self._resolve_output(description, output_dir)
        out.mkdir(parents=True, exist_ok=True)
        files: List[str] = []

        slug = re.sub(r"[^a-z0-9-]", "-", description.lower()[:40]).strip("-") or "sentinel-site"
        pkg = {
            "name": slug,
            "version": "0.1.0",
            "private": True,
            "scripts": {
                "dev": "next dev",
                "build": "next build",
                "start": "next start",
            },
            "dependencies": {
                "next": "14.2.0",
                "react": "^18.2.0",
                "react-dom": "^18.2.0",
            },
            "devDependencies": {
                "tailwindcss": "^3.4.0",
                "postcss": "^8.4.0",
                "autoprefixer": "^10.4.0",
                "typescript": "^5.0.0",
                "@types/node": "^20.0.0",
                "@types/react": "^18.0.0",
            },
        }
        files.append(self._write(out / "package.json", json.dumps(pkg, indent=2)))
        files.append(self._write(out / "next.config.js", "module.exports = { reactStrictMode: true };\n"))
        files.append(self._write(out / "tailwind.config.js", _TAILWIND))
        files.append(self._write(out / "postcss.config.js", "module.exports = { plugins: { tailwindcss: {}, autoprefixer: {} } };\n"))
        (out / "app").mkdir(exist_ok=True)
        files.append(self._write(out / "app" / "layout.tsx", _LAYOUT))
        files.append(self._write(out / "app" / "page.tsx", _PAGE.format(title=description[:60])))
        files.append(self._write(out / "app" / "globals.css", "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n"))

        launch = f'cd /d "{out}" && npm install && npm run dev'
        return BuildResult(
            success=True,
            builder=self.name,
            project_type=self.project_type,
            output_dir=str(out),
            entry_point=str(out / "app" / "page.tsx"),
            launch_command=launch,
            files=files,
            build_logs="Next.js scaffold created. Dev server: http://localhost:3000",
            artifact_type="app",
        )

    def _resolve_output(self, description: str, output_dir: Optional[str]) -> Path:
        if output_dir:
            return Path(output_dir).expanduser().resolve()
        return Path.home() / "Desktop" / "sentinel_website"

    def _write(self, path: Path, content: str) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return str(path)


_TAILWIND = """\
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./app/**/*.{js,ts,jsx,tsx}'],
  theme: { extend: {} },
  plugins: [],
};
"""

_LAYOUT = """\
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-slate-900 text-white min-h-screen">{children}</body>
    </html>
  );
}
"""

_PAGE = """\
export default function Home() {{
  return (
    <main className="p-12 max-w-4xl mx-auto">
      <h1 className="text-4xl font-bold text-emerald-400 mb-4">{title}</h1>
      <p className="text-slate-300">Built with Sentinel Web Builder (Next.js + Tailwind).</p>
    </main>
  );
}}
"""
