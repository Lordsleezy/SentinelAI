# Guardian Toolchain

## Bootstrap Manager

`workers/guardian/bootstrap_manager.py`

On startup (and via `POST /api/guardian/bootstrap`):

1. Check required tools
2. Download missing (GitHub releases)
3. Verify SHA256 when manifest provides hash
4. Extract to `tools/<id>/`
5. Update Nuclei templates
6. Refresh registry + emit UI events

## Tool Registry

`workers/guardian/guardian_tool_registry_store.py`  
Persistence: `memory/vault/guardian_tool_registry.json`

Per tool:

- name
- version
- install_path
- install_status (`installed` | `missing` | `optional` for ZAP)
- health
- last_verified
- category (`core` | `extended`)

## Core tools

httpx, subfinder, katana, nuclei, dnsx, naabu

## Extended tools

amass, assetfinder, ffuf, gowitness, zap (daemon — optional, guided install if missing)

## API

- `GET /api/guardian/bootstrap/status`
- `POST /api/guardian/bootstrap` (unchanged path, uses Bootstrap Manager)
- `GET /api/guardian/tools/status` (registry + legacy diagnostics)
