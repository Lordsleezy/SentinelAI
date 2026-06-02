<#
.SYNOPSIS
    Builds the SentinelAI CONSUMER installer (no Earn, trial active).

.PARAMETER Version
    Semantic version, defaults to package.json version.

.EXAMPLE
    .\build_consumer.ps1 -Version 1.0.2
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
Write-Host "`n=== CONSUMER BUILD v$Version ===" -ForegroundColor Cyan

# ── 1. Generate build_info.py ─────────────────────────────────────────────────
Write-Host "`n[1/4] Generating build_info.py..."
& "$PSScriptRoot\generate_build_info.ps1" -BuildType consumer -Version $Version

# ── 2. Build Python backend (consumer spec) ───────────────────────────────────
Write-Host "`n[2/4] PyInstaller — consumer backend..."
$BackendDist = "$Root\backend_dist_consumer"
if (Test-Path $BackendDist) { Remove-Item $BackendDist -Recurse -Force }
& pyinstaller build_backend_consumer.spec `
    --distpath "$BackendDist" `
    --workpath "$Root\build_tmp\consumer" `
    --noconfirm `
    --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (consumer)" }

# ── 3. Copy backend into electron extraResources location ─────────────────────
Write-Host "`n[3/4] Staging backend for electron-builder..."
$Staging = "$Root\backend_dist"
if (Test-Path $Staging) { Remove-Item $Staging -Recurse -Force }
Copy-Item "$BackendDist\sentinel_backend" $Staging -Recurse

# ── 4. electron-builder — consumer installer ──────────────────────────────────
Write-Host "`n[4/4] electron-builder — CONSUMER installer..."
$InstallerDist = "$Root\installer_dist_consumer"
if (Test-Path $InstallerDist) { Remove-Item $InstallerDist -Recurse -Force }
Set-Location "$Root\desktop-shell"
& npx electron-builder --win --publish never `
    --config.directories.output="$InstallerDist" `
    --config.extraMetadata.version="$Version" `
    --config.productName="SentinelAI"
if ($LASTEXITCODE -ne 0) { throw "electron-builder failed (consumer)" }

Set-Location $Root
Write-Host "`n=== CONSUMER BUILD COMPLETE ===" -ForegroundColor Green
Write-Host "Installer: $InstallerDist" -ForegroundColor Yellow
