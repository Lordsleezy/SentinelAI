# Installer Validation — SentinelAISetup.exe

**Target artifact:** `installer_dist/SentinelAISetup.exe`  
**Version:** `1.0.0-beta.1`  
**Builder:** `scripts/build_installer.bat` → electron-builder NSIS

## Requirements checklist

| Requirement | Implementation | Verified |
|-------------|----------------|----------|
| Install Sentinel | NSIS installs Electron app + bundled `sentinel_backend` | Config ✓ / EXE pending build |
| Install updater | `electron-updater` in `desktop-shell/main.js` (autoDownload, GitHub publish) | Code ✓ |
| Dependency manager | Backend `core/dependency_manager` in repo; wizard + Settings → Downloads | Code ✓ |
| Uninstall entry | `uninstallDisplayName: "Sentinel AI"`, NSIS GUID registered | Config ✓ |
| Desktop shortcut | `createDesktopShortcut: true` | Config ✓ |
| Launch onboarding wizard | `runAfterFinish: true` + `isWizardNeeded()` on first Electron run | Code ✓ |
| Installer filename | `artifactName: "SentinelAISetup.${ext}"` | Config ✓ |

## Build steps

```powershell
.\scripts\generate_build_info.ps1 -BuildType beta -Version 1.0.0-beta.1
.\scripts\build_installer.bat
.\scripts\validate_installer.ps1
```

Prerequisites: Python venv with PyInstaller, Node 16+, `npm install` in `desktop-shell/`.

## Validation script

`scripts/validate_installer.ps1` checks:

- `SentinelAISetup*.exe` exists in `installer_dist/`
- Size > 50 MB (typical with backend bundle)
- NSIS flags (shortcut, uninstall name, runAfterFinish, electron-updater)

## Clean Windows VM test (manual)

1. Fresh Windows 10/11 x64 VM, no Python required for end user.
2. Run `SentinelAISetup.exe` as standard user (elevate if NSIS per-machine).
3. Confirm **Add/Remove Programs** lists “Sentinel AI”.
4. Confirm desktop shortcut launches app.
5. Confirm setup wizard appears (no `%APPDATA%/<app>/.wizard_done`).
6. Settings → Downloads → Scan shows components.
7. Uninstall removes shortcut and program files; user data under `%APPDATA%` retained by design.

## Current status

| Check | Result |
|-------|--------|
| NSIS configuration | PASS |
| `electron-updater` wired | PASS |
| Built `SentinelAISetup.exe` on disk | **PENDING** — run `build_installer.bat` on release machine |

## Post-build

Upload `SentinelAISetup.exe` to GitHub Release `v1.0.0-beta.1`. Beta portal (`/api/beta/release`) resolves download URL from GitHub API automatically.
