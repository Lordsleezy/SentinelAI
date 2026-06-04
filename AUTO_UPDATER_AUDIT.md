# Auto-Updater Audit Report

**Date:** 2026-06-02  
**Scope:** `core/updater/auto_updater.py`, Electron `electron-updater`, GitHub Releases, installer pipeline  
**Method:** Static code audit, version-comparison simulation, live `check_for_updates()` against `Lordsleezy/SentinelAI`  
**Constraint:** No architecture redesign; findings only (repairs documented, not applied in this pass).

---

## Executive Summary

Sentinel runs **two parallel update mechanisms** that are not fully integrated:

| Path | Technology | Auto-install? | Updates Python backend? | Updates Electron shell? |
|------|------------|---------------|-------------------------|-------------------------|
| **A** | `electron-updater` in `desktop-shell/main.js` | Yes (`quitAndInstall`) | Only if bundled in new Electron build | Yes |
| **B** | `core/updater/auto_updater.py` + Settings UI | **No** — downloads verified file to `data/updates/` | No — separate installer artifact | No |

**Release-critical gap:** Pushing code + a GitHub Release with only a loose `.exe` does **not** guarantee in-place auto-update for installed users unless you also publish an **electron-builder** update feed (`latest.yml` + blockmap) via `electron-builder --publish`. Current `npm run dist` uses `--publish never`.

**Overall readiness:** **WARNING** — check/download/verify paths exist; end-to-end silent upgrade for existing installs is **not fully validated**.

---

## 1. Update Flow

### Documented flow (dual paths)

#### Path A — Electron (`electron-updater`)

```
App ready (main.js initAutoUpdater)
  → autoUpdater.checkForUpdates()  [immediate + every 4h]
  → GitHub (via electron-builder publish config: Lordsleezy/SentinelAI)
  → Compare app version (package.json / built app) vs remote latest.yml
  → autoDownload = true
  → 'update-downloaded' → IPC 'update-available' → orb update banner
  → User click → ipc 'install-update' → autoUpdater.quitAndInstall()
  → Relaunch
```

#### Path B — Python (`AutoUpdater`)

```
Backend start (start_backend) OR Settings → Updates → Check
  → POST /api/updates/check
  → GET https://api.github.com/repos/Lordsleezy/SentinelAI/releases
  → _version_newer() digit compare vs build_info.BUILD_VERSION
  → State in data/updates/update_state.json
  → POST /api/updates/download → background stream to data/updates/pending_*
  → SHA-256 vs release notes / sidecar
  → apply_pending_notification() → message only; NO installer execution
```

### Failure points

| Step | Path | Failure mode | Recovery |
|------|------|--------------|----------|
| Network down | A, B | Silent catch / `ok: false` | App continues; retry on interval |
| GitHub rate limit | B | Exception → `check failed` | Needs `GITHUB_TOKEN` |
| No published releases | B | `available: null` | User stays on current version |
| Draft release | B | **Not visible** — API lists published only | N/A |
| Version compare wrong | B | Numeric-only regex (see §5) | Wrong skip or wrong offer |
| Asset mismatch | B | Picks first `.exe`/`.zip`; tag vs filename can differ | User confusion (observed: v1.0.2 asset named `1.0.1.exe`) |
| Checksum missing | B | Download accepted without hash verify | **WARNING** — supply-chain risk |
| Checksum mismatch | B | File deleted | Safe |
| Partial download | B | Exception; partial file may remain on disk | **WARNING** — no explicit cleanup except mismatch delete |
| Install step | B | **Not implemented** | User must run installer manually |
| electron-updater missing | A | Logged; no updates | Dev mode |
| publish never in build | A | No `latest.yml` on release | **FAIL** for silent Electron update |
| Rollback | B | Metadata only | **FAIL** — no automatic restore |

---

## 2. Release Compatibility

| Change type | Updated by GitHub Release alone? | Notes |
|-------------|----------------------------------|-------|
| Python (`desktop_app.py`, workers) | Only if new **Electron build** rebundles `backend_dist/sentinel_backend` in `extraResources` | Path B download does not apply code in-place |
| Electron (`main.js`, orb.html) | Path A if electron publish feed present; else full reinstall via downloaded `.exe` | |
| Frontend (`orb.html`) | Same as Electron | |
| Assets (`desktop-shell/assets`) | Bundled in Electron build | |
| Models (Ollama) | **Not** in release artifact | Pulled at runtime by model runtime |
| Configuration | User `~/.sentinelai`, `config/`, `.env` preserved on upgrade if installer does not wipe | NSIS only writes `install.flag` |
| Memory schema | **Not** migrated by updater | User DBs persist under `memory/`, `data/` |
| Guardian / Vision | Code-only via new backend bundle | |

**Verdict:** A GitHub Release **alone** does not update all components unless the release artifact is a **full new installer/app package** built from a complete `build_both` / `electron-builder` pipeline.

---

## 3. Installer Verification

| Item | Status | Evidence |
|------|--------|----------|
| `SentinelAISetup.exe` naming | **PASS** | `package.json` → `"artifactName": "SentinelAISetup.${ext}"` |
| NSIS installer | **PASS** | `win.target: nsis`, `installer.nsh` custom install flag |
| electron-builder config | **PASS** | `publish.provider: github`, `appId`, `extraResources` for backend |
| Updater ↔ installer compatibility | **WARNING** | Python updater downloads `.exe` but does not launch it; Electron path needs published update metadata |
| Live release asset | **WARNING** | Audit found release `v1.0.2` with asset `SentinelAI.Setup.1.0.1.exe` (name/tag mismatch) |

---

## 4. Rollback

| Capability | Status | Detail |
|------------|--------|--------|
| `rollback_version` in state | **PASS** | Set when download completes |
| `GET /api/updates/rollback` | **PASS** | Returns metadata |
| Execute rollback | **FAIL** | `rollback_info()` note: manual reinstall only |
| Failed update recovery | **WARNING** | App does not brick; user stays on old build; pending file may linger |
| Auto-revert install | **FAIL** | Not implemented |

**Brick risk:** Low — worst case is failed download or user remains on previous version; no forced partial overwrite of app dir by Python updater.

---

## 5. Version Control

Implementation: `_version_newer()` — extracts integers with `re.findall(r"\d+", v)[:4]`, lexicographic numeric compare.

### Simulated ordering

| Remote | Current | Result | Correct? |
|--------|---------|--------|------------|
| 1.0.0-beta.2 | 1.0.0-beta.1 | newer | Yes |
| 1.0.0-beta.10 | 1.0.0-beta.9 | newer | Yes |
| 1.0.1 | 1.0.0 | newer | Yes |
| 1.0.0-beta.1 | 1.0.0 | newer | **Debatable** (offers beta over stable) |
| 1.0.0 | 1.0.0-beta.1 | not newer | **FAIL** for semver — stable not offered over beta build |

**Channels**

| Channel | Logic | Status |
|---------|-------|--------|
| `beta` | First release newer than current (includes prerelease) | **PASS** with digit caveats |
| `stable` | First **non-prerelease** newer than current | **PASS** |

**Prerelease:** Honored for stable channel (skipped). Beta channel ignores `prerelease` flag.

---

## 6. GitHub Release Audit

| Release type | Supported by Python updater? | Notes |
|--------------|------------------------------|-------|
| Published | **PASS** | `GET /repos/.../releases` |
| Draft | **FAIL** | Drafts excluded from API list |
| Pre-release | **PASS** (beta channel) | Included in beta selection |
| Stable (non-prerelease) | **PASS** (stable channel) | |

**electron-updater:** Uses GitHub provider from `package.json` `build.publish`; requires published release with compatible update artifacts (typically from `electron-builder --publish`).

---

## 7. Update Manifest

| Expected path | Status |
|---------------|--------|
| `data/release/update_manifest.json` (per `RELEASE_PROCESS.md`) | **WARNING** — generated at runtime via `ReleaseManager.generate_manifest()`; not present until backend runs |
| `data/release/update_manifest.json` (audit spec name) | **FAIL** — repo uses `release_manifest.json`, not `update_manifest.json` |

**Required fields (audit spec) vs implementation:**

| Field | In manifest? |
|-------|----------------|
| version | **PASS** |
| channel | **PASS** |
| release_date | **FAIL** — uses `generated_at` |
| minimum_supported_version | **FAIL** |
| force_update | **FAIL** |
| kill_switch | **FAIL** |
| beta_active | **FAIL** |

Kill-switch / force-update are implemented elsewhere (`killswitch_checker`, license policy), not in release manifest.

---

## 8. Admin Controls

| Control | Implemented? | Mechanism |
|---------|--------------|-----------|
| Disable updates | **FAIL** | No global flag in `AutoUpdater` or `main.js` |
| Force updates | **FAIL** | No `force_update` enforcement |
| Force minimum version | **PARTIAL** | `killswitch_checker` optional `min_version` (uses `SENTINEL_VERSION` env, often unset) |
| End beta remotely | **PASS** | License `apply_remote_policy`: `restricted_mode`, `beta_expires_at` via `https://sentinelprime.org/api/validate` |
| Disable features remotely | **PASS** | `remote_features_disabled` in license policy |
| Update channel switch | **PASS** | `POST /api/updates/channel` + `data/updates/update_state.json` |
| Remote killswitch | **PASS** | `GET https://sentinelprime.org/api/killswitch` |

---

## 9. Security

| Control | Status | Detail |
|---------|--------|--------|
| SHA-256 validation | **PARTIAL** | Computed on download; compared only if hash in release body or `data/updates/{asset}.sha256` |
| Release source validation | **PARTIAL** | Hardcoded repo `Lordsleezy/SentinelAI` / env override |
| Corrupt package | **PASS** | Mismatch → file deleted |
| Partial download | **WARNING** | Exception path may leave incomplete file |
| HTTPS | **PASS** | httpx to GitHub |
| GITHUB_TOKEN | Optional | Rate limits |

---

## 10. Stress Test (Code-Path Analysis)

| Scenario | Expected behavior | Status |
|----------|-------------------|--------|
| No internet | `check_for_updates` → `ok: false`; Electron catches error | **PASS** |
| GitHub unavailable | Same | **PASS** |
| Corrupt package | Hash mismatch → delete | **PASS** (if hash provided) |
| Interrupted download | Exception; possible orphan file | **WARNING** |
| Rollback | Metadata only | **FAIL** execution |
| Version downgrade attempt | `_version_newer` false → no offer | **PASS** (won't auto-downgrade) |
| Brick install | No in-place overwrite by Python layer | **PASS** |

---

## 11. Update Diagnostics UI

| Requirement | Status |
|-------------|--------|
| Settings → Updates → Diagnostics | **FAIL** |
| Settings → Updates (basic) | **PASS** — version, channel, last check, last update, available |
| Missing fields | Last Download, Last Install, Last Failure, GitHub Connectivity, Update Status |

Electron update banner (`#update-banner`) is separate from Python diagnostics.

---

## 12. Subsystem Scorecard

| Subsystem | Result |
|-----------|--------|
| Python update check (GitHub API) | **PASS** |
| Python background download | **PASS** |
| Python SHA-256 verify | **WARNING** (optional hash) |
| Python install/apply | **FAIL** |
| Python rollback execution | **FAIL** |
| Version compare (semver) | **WARNING** |
| Beta/stable channels | **PASS** |
| Draft release support | **FAIL** |
| electron-updater wiring | **PASS** (code present) |
| electron-updater publish pipeline | **FAIL** (`--publish never`) |
| Installer NSIS / naming | **PASS** |
| Dual-path coordination | **FAIL** |
| `update_manifest.json` (full spec) | **FAIL** |
| Settings update diagnostics panel | **FAIL** |
| Admin kill-switch / min version | **WARNING** |
| Security (mandatory checksum) | **WARNING** |
| Brick safety | **PASS** |
| Live GitHub connectivity (audit run) | **PASS** — `check_for_updates()` returned `v1.0.2` for current `1.0.0-beta.1` |

---

## Success Criteria vs Current State

| Criterion | Met? |
|-----------|------|
| Push code → build → GitHub Release → auto-update without reinstall | **NO** — requires electron publish + full installer build; Python path does not install |
| Existing installs update automatically | **PARTIAL** — only via electron-updater if feed published; otherwise manual |

---

## Recommended Repairs (Documentation Only — Not Applied)

1. Publish releases with `electron-builder --publish always` (or CI) so `latest.yml` exists.  
2. Unify version comparison on proper semver (e.g. `packaging.version`).  
3. Run downloaded `SentinelAISetup.exe` silently or delegate exclusively to electron-updater (remove duplicate path).  
4. Require SHA-256 in release notes or mandatory sidecar for every asset.  
5. Implement `update_manifest.json` fields or extend `generate_manifest()` for `force_update`, `minimum_supported_version`, `beta_active`.  
6. Add Settings → Updates → Diagnostics panel wired to `update_state.json` + last error fields.  
7. Implement rollback execution or document manual procedure only.  
8. Add `updates_disabled` flag respected by both paths.

---

## Key Files

| File | Role |
|------|------|
| `core/updater/auto_updater.py` | GitHub check, download, checksum, state |
| `data/updates/update_state.json` | Channel, last check, pending download |
| `desktop-shell/main.js` | `initAutoUpdater`, `install-update` IPC |
| `desktop-shell/package.json` | Version, NSIS, `electron-updater`, GitHub publish |
| `desktop-shell/orb.html` | Settings → Updates UI, update banner |
| `desktop_app.py` | `/api/updates/*`, startup check |
| `core/release/release_manager.py` | `release_manifest.json` generation |
| `build_info.py` | `BUILD_VERSION` source of truth |
| `AUTO_UPDATER.md` | Operator docs |

---

*End of audit.*
