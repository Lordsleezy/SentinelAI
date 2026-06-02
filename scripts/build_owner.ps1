<#
.SYNOPSIS
    Builds the SentinelAI OWNER installer (includes Earn, trial bypassed).

    WARNING: This installer MUST NOT be publicly distributed.

.PARAMETER Version
    Semantic version, defaults to package.json version.

.EXAMPLE
    .\build_owner.ps1 -Version 1.0.2
#>
param([string]$Version = "")

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Root = Resolve-Path "$PSScriptRoot\.."
Set-Location $Root

# ── Resolve version ────────────────────────────────────────────────────────────
if (-not $Version) {
    $pkg = Get-Content "$Root\desktop-shell\package.json" | ConvertFrom-Json
    $Version = $pkg.version
}
Write-Host "`n=== OWNER BUILD v$Version ===" -ForegroundColor Magenta

# ── 1. Generate build_info.py ─────────────────────────────────────────────────
Write-Host "`n[1/4] Generating build_info.py..."
& "$PSScriptRoot\generate_build_info.ps1" -BuildType owner -Version $Version

# ── 2. Build Python backend (owner spec) ─────────────────────────────────────
Write-Host "`n[2/4] PyInstaller — owner backend..."
$BackendDist = "$Root\backend_dist_owner"
if (Test-Path $BackendDist) { Remove-Item $BackendDist -Recurse -Force }
& pyinstaller build_backend_owner.spec `
    --distpath "$BackendDist" `
    --workpath "$Root\build_tmp\owner" `
    --noconfirm `
    --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (owner)" }

# ── 3. Staging ────────────────────────────────────────────────────────────────
Write-Host "`n[3/4] Staging backend for electron-builder..."
$Staging = "$Root\backend_dist"
if (Test-Path $Staging) { Remove-Item $Staging -Recurse -Force }
Copy-Item "$BackendDist\sentinel_backend" $Staging -Recurse

# ── 4. electron-builder — owner installer ─────────────────────────────────────
Write-Host "`n[4/4] electron-builder — OWNER installer..."
$InstallerDist = "$Root\installer_dist_owner"
if (Test-Path $InstallerDist) { Remove-Item $InstallerDist -Recurse -Force }

# Set SENTINEL_OWNER_MODE so Electron main process also knows
$env:SENTINEL_OWNER_MODE = 'true'
Set-Location "$Root\desktop-shell"
& npx electron-builder --win --publish never `
    --config.directories.output="$InstallerDist" `
    --config.extraMetadata.version="$Version" `
    --config.productName="SentinelAI Owner"
if ($LASTEXITCODE -ne 0) { throw "electron-builder failed (owner)" }

$env:SENTINEL_OWNER_MODE = ''
Set-Location $Root
Write-Host "`n=== OWNER BUILD COMPLETE ===" -ForegroundColor Green
Write-Host "Installer: $InstallerDist" -ForegroundColor Yellow
Write-Host "!! DO NOT DISTRIBUTE THIS BUILD PUBLICLY !!" -ForegroundColor Red
