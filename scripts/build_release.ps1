# Full beta release build — version stamp + backend + installer
param(
    [string]$Version = "1.0.0-beta.1"
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent

& "$PSScriptRoot\generate_build_info.ps1" -BuildType beta -Version $Version
& "$PSScriptRoot\build_installer.bat"
& "$PSScriptRoot\validate_installer.ps1"

Write-Host "[build_release] Done. Upload installer_dist/SentinelAISetup.exe to GitHub Release v$Version"
Write-Host "[build_release] For auto-update via electron-updater (latest.yml), run: scripts\build_release_publish.ps1 -Version $Version"
