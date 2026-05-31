# SentinelAI — Full Codebase Audit Report
**Audit Date:** 2026-05-30
**Scope:** Complete codebase review for build success and packaged distribution

---

## Executive Summary

The codebase is **functionally rich** (~30k LoC, 50+ workers) but has **build-blocking issues** that will cause both PyInstaller and GitHub Actions to fail. The bulk of the work needed is in three files: `build_backend.spec`, `requirements.txt`, and `.github/workflows/build.yml`. There is also a packaged-mode launch bug in `desktop-shell/main.js`.

---

## CRITICAL (will crash the app or build)

### C1. PyInstaller spec references modules that don't exist
**File:** `build_backend.spec`
**Issue:** `hiddenimports` lists modules whose `.py` files do not exist in the repo:
- `workers.capability.gap_detector`
- `workers.capability.capability_finder`
- `workers.capability.capability_installer`
- `workers.capability.capability_builder`
- `workers.capability.registry`
- `workers.earn.sources.bounty_targets`
- `workers.earn.sources.remoteok_scanner`
- `workers.earn.sources.freelancer_scanner`
- `workers.earn.sources.upwork_scanner`
- `market.openbb_bridge`
- `market.freqtrade_manager`

`workers/capability/` contains only `__init__.py`. `workers/earn/sources/` does not exist. `market/` does not exist as a top-level package.

**Impact:** PyInstaller will raise `ModuleNotFoundError` and abort.

### C2. requirements.txt is incomplete
**File:** `requirements.txt`
**Issue:** Missing several packages that are imported by the codebase (or required by build):
- `anthropic` (used by orchestration confidence escalation)
- `sentence-transformers` (RAG embeddings, commented out)
- `requests` (most workers)
- `beautifulsoup4` (web_worker)
- `feedparser` (news worker)
- `flask-socketio` (real-time HUD)
- `python-telegram-bot` / `telethon` (messaging)
- `spotipy` (entertainment)
- `gcsa` (Google Calendar)
- `pyyaml` (worker configs)
- `numpy` (RAG vector ops)

**Impact:** `pip install -r requirements.txt` succeeds but runtime imports fail.

### C3. GitHub Actions workflow uses batch syntax in PowerShell shell
**File:** `.github/workflows/build.yml`
**Issue:** windows-2025 runners default to **PowerShell 7 (`pwsh`)**. The workflow uses cmd.exe / batch syntax which does not parse in PowerShell:
- `if not exist "..." (echo ... && exit 1)` (line 49) → PowerShell parse error
- `if exist "backend_dist" rmdir /s /q backend_dist` (line 55) → PowerShell parse error

**Impact:** Verify-backend-build and copy steps fail; backend is never copied to `backend_dist/`, so Electron build cannot bundle it.

### C4. main.js does not detect packaged mode
**File:** `desktop-shell/main.js` line 137–192
**Issue:** `launchBackend()` always spawns `python desktop_app.py` from the source directory. In an installed `.exe`, the Python source is not available — only the bundled `sentinel_backend.exe` under `resources/sentinel_backend/`.

**Impact:** The installed app will fail to start the backend (Python won't be found, or source file won't exist).

### C5. Empty `workers/earn/` and `workers/earn/sources/` packages
**Issue:** `workers/earn/` has no `__init__.py`. `workers/earn/sources/` doesn't exist. PyInstaller will fail to import.

**Impact:** PyInstaller raises ModuleNotFoundError if these are kept in hiddenimports.

### C6. `market/` package doesn't exist
**Issue:** `market.openbb_bridge` and `market.freqtrade_manager` are in spec hiddenimports but there is no `market/` package at the project root. Only `memory/vault/market/` exists (a gitkeep-only data dir).

**Impact:** PyInstaller fails to import.

---

## WARNING (feature will fail silently)

### W1. `scripts/generate_icon.py` uses relative paths
**File:** `scripts/generate_icon.py`
**Issue:** Uses `os.makedirs('desktop-shell/assets', exist_ok=True)` which only works when CWD is the project root. The workflow runs it without `cd`, relying on default CWD.
**Status:** Works for current workflow but fragile. icon.ico is already present, so this is a minor warning.

### W2. Backend datas paths in spec assume runtime CWD
**File:** `build_backend.spec` line 14–18
**Issue:** Datas reference `memory/vault`, `config`, `.env.example`. These directories exist but may not have content (gitkeep only).
**Impact:** Spec works at build time; runtime path resolution may need adjustment.

### W3. Some orchestration workers may import optional libs without try/except
**Issue:** `workers/orchestration/rag.py` imports `chromadb` and `sentence_transformers` — if not installed, RAG silently disabled. **This is OK**, but if it raises ImportError at module top, Flask app won't start.

### W4. `flask-socketio` import in desktop_app.py is conditional (good)
**Status:** Already guarded with try/except. No fix needed.

---

## MINOR (cosmetic or non-breaking)

### M1. `desktop-shell/electron_logs/` and `backend.pid` should be gitignored
### M2. AUDIT_REPORT.md previously contained Sentinel Earn audit (now overwritten with this report)
### M3. `package.json` files: `["**/*"]` will include node_modules in the asar bundle (electron-builder will dedupe but it bloats)

---

## FIX PLAN (applied in this session)

1. **F1** — Rewrite `build_backend.spec` to only reference modules that exist; create stub `workers/capability/` modules if needed.
2. **F2** — Update `requirements.txt` with all needed packages.
3. **F3** — Rewrite `.github/workflows/build.yml` with PowerShell-compatible commands and explicit fail-fast verification.
4. **F4** — Update `main.js` `launchBackend()` to detect `app.isPackaged` and spawn the bundled `sentinel_backend.exe` in packaged mode.
5. **F5** — Add `workers/earn/__init__.py` and create the missing `workers/earn/sources/` package with minimal stubs (or remove from spec).
6. **F6** — Either create `market/` package with stubs or remove from spec (the build doesn't need it).
7. **F7** — Implement `workers/capability/*` as minimal stubs (registry, gap_detector, etc.) OR remove from spec.

Outcome target: GitHub Actions runs clean, produces `installer_dist/SentinelAI Setup.exe` > 200MB.
