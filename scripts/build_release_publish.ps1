# Beta release build + publish to GitHub (generates latest.yml for electron-updater)
param(
    [string]$Version = "1.0.0-beta.1"
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent

& "$PSScriptRoot\generate_build_info.ps1" -BuildType beta -Version $Version
python "$PSScriptRoot\generate_installer_icons.py"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$env:SENTINEL_NONINTERACTIVE = "1"
& "$PSScriptRoot\build_backend.bat"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Push-Location "$root\desktop-shell"
if (-not (Test-Path node_modules)) { npm install }
npm run dist:publish
if ($LASTEXITCODE -ne 0) { Pop-Location; exit $LASTEXITCODE }
Pop-Location

& "$PSScriptRoot\validate_installer.ps1"
& "$PSScriptRoot\validate_updater.py"

Write-Host "[build_release_publish] Published $Version - verify latest.yml on GitHub Release"
