# Guardian Bundled Toolchain

Sentinel ships **Guardian Core** — ProjectDiscovery tools used by the assessment pipeline — without requiring manual installs.

## Layout

| Tool | Bundled path |
|------|----------------|
| httpx | `tools/httpx/httpx.exe` |
| Subfinder | `tools/subfinder/subfinder.exe` |
| Katana | `tools/katana/katana.exe` |
| Nuclei | `tools/nuclei/nuclei.exe` |

Installer repair sources (read-only): `installer_assets/guardian_core/<tool>/`

## Resolution order

1. **Sentinel bundled** — `tools/<tool>/`
2. **User-installed** — e.g. `C:\Tools\<tool>.exe`
3. **PATH** — `shutil.which`

## Bootstrap

On backend startup, `guardian_bootstrap`:

- **Auto-downloads** latest `*_windows_amd64.zip` from ProjectDiscovery GitHub releases when `tools/` and `installer_assets/guardian_core/` are empty (`guardian_tool_fetcher.py`)
- Verifies each core binary
- Copies or extracts from `installer_assets/guardian_core/` when bundled copy is missing
- Logs `[GUARDIAN] Bundled tools verified` with per-tool ✓/✗
- Runs `nuclei -update-templates` when nuclei is available (best-effort)

Stage manually (dev / installer build):

```powershell
.\scripts\stage_guardian_core.ps1
```

State: `memory/vault/guardian_bootstrap.json`

Manual repair:

```http
POST /api/guardian/bootstrap
{"force": true}
```

## Tool Status panel

Guardian UI shows per tool:

- `✓ Bundled` — using `tools/<tool>/`
- `✓ System` — user path or PATH
- `✗ Missing` — not available (e.g. ZAP, Amass)

## Building the installer

Stage binaries before PyInstaller / installer build:

```powershell
.\scripts\stage_guardian_core.ps1
```

This downloads latest ProjectDiscovery Windows amd64 releases into `tools/` and `installer_assets/guardian_core/`.

`build_backend.spec` includes `installer_assets/guardian_core` and populated `tools/*` directories in the frozen bundle.

## Optional tools

**ZAP** and **Amass** are not bundled; they remain optional (Docker ZAP on `:8090`, manual Amass install).
