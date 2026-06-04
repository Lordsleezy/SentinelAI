#!/usr/bin/env bash
# Build Linux AppImage + deb (run inside WSL Ubuntu with Node 18+).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d "$ROOT/backend_dist/sentinel_backend" ]]; then
  echo "[linux] ERROR: backend_dist/sentinel_backend missing. Run scripts/build_backend.bat on Windows first."
  exit 1
fi

if [[ ! -f "$ROOT/desktop-shell/assets/icon.ico" ]]; then
  python3 "$ROOT/scripts/generate_installer_icons.py" || python "$ROOT/scripts/generate_installer_icons.py"
fi

cd "$ROOT/desktop-shell"
if [[ ! -d node_modules ]]; then
  npm install
fi
npm run dist:linux
echo "[linux] Artifacts:"
ls -la "$ROOT/installer_dist/"*.AppImage "$ROOT/installer_dist/"*.deb 2>/dev/null || ls -la "$ROOT/installer_dist/"
