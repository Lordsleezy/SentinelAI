# AppData .env Fix (EPERM in Program Files)

## Problem
Packaged startup called `ensureEnvFile()` which wrote `.env` under `process.resourcesPath` (`C:\Program Files\SentinelAI\resources\`), causing **EPERM** on copy from `.env.example`.

## Fix
- **Electron** (`desktop-shell/main.js`): `app.setPath('userData', %APPDATA%\SentinelAI)`; `.env`, `data/`, `config/`, and `backend.pid` use userData only; `.env.example` read from resources (read-only).
- **Backend** (`core/app_paths.py`, `db.py`, `workers/lazy_init.py`, `desktop_app.py`): honor `SENTINELAI_USER_DATA`, `SENTINELAI_ENV_PATH`, `SENTINELAI_DATA_DIR` injected by Electron.
- **Setup wizard**: `/api/setup/*`, `/api/onboarding/*`, etc. allowed without bearer token so first-run wizard can call the backend from `setup_wizard.html`.
- **Startup errors**: removed pip/venv hints for packaged installs.

## Build output
- **`installer_dist3/SentinelAISetup.exe`** (latest)
- Copied to **`installer_dist/SentinelAISetup.exe`** when not file-locked

## Verified
| Test | Result |
|------|--------|
| `.env` created at `%APPDATA%\SentinelAI\.env` | PASS |
| Backend `/api/ping` | PASS (200) |
| `/api/setup/scan` without auth | PASS (200) |
| No write under `Program Files\...\resources\.env` | PASS (path moved to AppData) |

## Manual install test
1. Run `installer_dist3\SentinelAISetup.exe` (or `installer_dist\SentinelAISetup.exe`).
2. Confirm no EPERM dialog.
3. Complete first-run wizard → Sentinel AI orb opens.
