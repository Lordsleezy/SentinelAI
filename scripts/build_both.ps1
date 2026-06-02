<#
.SYNOPSIS
    Builds both the CONSUMER and OWNER installers sequentially.

.PARAMETER Version
    Semantic version. If omitted, reads from desktop-shell/package.json.

.EXAMPLE
    .\build_both.ps1 -Version 1.0.2
#>
param([string]$Version = "")

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $Version) {
    $pkg = Get-Content "$PSScriptRoot\..\desktop-shell\package.json" | ConvertFrom-Json
    $Version = $pkg.version
}

Write-Host "`n>>> Building CONSUMER v$Version..." -ForegroundColor Cyan
& "$PSScriptRoot\build_consumer.ps1" -Version $Version

Write-Host "`n>>> Building OWNER v$Version..." -ForegroundColor Magenta
& "$PSScriptRoot\build_owner.ps1" -Version $Version

Write-Host "`n=== BOTH BUILDS COMPLETE ===" -ForegroundColor Green
Write-Host "Consumer: $PSScriptRoot\..\installer_dist_consumer" -ForegroundColor Cyan
Write-Host "Owner:    $PSScriptRoot\..\installer_dist_owner" -ForegroundColor Magenta
