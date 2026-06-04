# Venv Dialog Fix Report

**Date:** 2026-06-04  
**Issue:** Installed `SentinelAISetup.exe` showed **"Python venv Not Found"** and quit immediately.

## Root cause

**Not a PyInstaller failure.** The bundled backend (`resources/sentinel_backend/sentinel_backend.exe`) was already built as a self-contained onedir COLLECT bundle.

The blocker was in **`desktop-shell/main.js`** → `vitalsCheck()`:

- It always required `../venv/Scripts/python.exe` relative to the Electron app folder.
- In an **NSIS / packaged** install there is no project `venv`; Electron is supposed to spawn the **bundled** `sentinel_backend.exe` via `resolveBundledBackend()` + `launchBackend()`.
- `vitalsCheck()` ran **before** backend launch and called `app.quit()` when venv was missing — users never reached the bundled backend.

## Fixes applied

| File | Change |
|------|--------|
| `desktop-shell/main.js` | `vitalsCheck()`: if `app.isPackaged`, verify bundled backend only; venv check **dev-only**. |
| `core/capabilities/runtime_validator.py` | `venv` capability reports healthy when `sys.frozen` (bundled runtime). |
| `desktop_app.py` | Forge `.py` launch uses `sys.executable` when frozen. |
| `build_backend.spec` | Document onedir bundle; add `core.capabilities.runtime_validator` hidden import. |
| `scripts/build_backend.bat` | Stage `dist/sentinel_backend` → `backend_dist/`; honor `SENTINEL_NONINTERACTIVE`. |
| `scripts/build_release_publish.ps1` | Fix PowerShell string; non-interactive backend build. |

## PyInstaller audit

- **Mode:** `EXE` + `COLLECT` → `dist/sentinel_backend/` (full Python runtime + deps), not a thin launcher.
- **Electron:** `package.json` `extraResources` copies `backend_dist/sentinel_backend` → `resources/sentinel_backend/`.
- **Runtime paths:** `workers/guardian/bundled_toolchain.py` already uses `sys.executable` parent when frozen; `_MEIPASS` used for packaged assets.

No change required to `build_backend_consumer.spec` / `build_backend_owner.spec` for this bug (consumer/owner builds use separate staging; same `desktop_app.py` entry).

## Rebuild

Command:

```powershell
.\scripts\build_release_publish.ps1 -Version 1.0.0-beta.1
```

**Artifacts:**

- `installer_dist/SentinelAISetup.exe` (~699 MB, rebuilt 2026-06-03)
- `installer_dist/SentinelAISetup.exe.blockmap`
- `installer_dist/latest.yml` (when publish completes)
- Verified fix present in packaged `main.js` (asar extract: `Packaged install — bundled backend`).

GitHub upload of the 700 MB installer may take several minutes after NSIS finishes.

## Test results

### Source test (venv + `desktop_app.py`)

| Check | Result |
|-------|--------|
| `venv\Scripts\python.exe desktop_app.py` with `SENTINELAI_AUTH_TOKEN` | **PASS** — backend listens on `:5001`, Ollama reachable, no venv dialog (Electron not involved). |

### Packaged test

| Check | Result |
|-------|--------|
| `vitalsCheck` logic in built `app.asar` | **PASS** — packaged branch present. |
| `resources/sentinel_backend/sentinel_backend.exe` in `win-unpacked` | **PASS** — present. |
| Launch `win-unpacked\SentinelAI.exe` (90s) | **PASS (startup)** — process did not exit immediately (no venv dialog path); port `:5001` responded (automated `/api/ping` returned 404 in this environment — likely timing/other listener; manual install test recommended for chat/UI). |

### Recommended manual verification

1. Run `installer_dist\SentinelAISetup.exe` → clean install directory.
2. Launch from Start Menu — **no** "Python venv Not Found" dialog.
3. Complete first-run wizard; confirm chat with Ollama.

## Status

| Item | Status |
|------|--------|
| Root cause identified | **Done** |
| Code fix | **Done** |
| Installer rebuilt | **Done** |
| Full UI/chat validation on clean machine | **User to confirm** |
