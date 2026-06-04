# Auto-Updater

**Module:** `core/updater/auto_updater.py`  
**State:** `data/updates/update_state.json`  
**API:** `/api/updates/*`

## Source

GitHub Releases for `Lordsleezy/SentinelAI` (override with `SENTINEL_GITHUB_REPO`).

## Channels

| Channel | Behavior |
|---------|----------|
| `beta` | Latest release (including prerelease) newer than current version |
| `stable` | Latest non-prerelease only |

## Flow

1. `POST /api/updates/check` — query GitHub API
2. `POST /api/updates/download` — background download to `data/updates/pending_*`
3. SHA-256 verified against release notes or sidecar `.sha256`
4. Rollback metadata stored (`rollback_version` in state)

## Settings UI

**Settings → Updates** shows current version, channel, last check/update, and available release.

## Environment

- `GITHUB_TOKEN` — optional, raises rate limits
- `SENTINEL_GITHUB_REPO` — `owner/repo`

## Install paths

1. **electron-updater** (primary): `npm run dist:publish` uploads `latest.yml` + blockmaps. App checks every 4h; banner → Restart.
2. **Python updater** (fallback): Settings → Updates → Download → Install runs NSIS `/S` on `SentinelAISetup.exe`.

## Rollback

`POST /api/updates/rollback/execute` — archive or re-fetch prior installer from GitHub tag.

## Manifest

`data/release/update_manifest.json` — `force_update`, `kill_switch`, `minimum_supported_version`, `beta_active`.

## Validation

```bash
python scripts/validate_updater.py
```

No user data directories are deleted during update.
