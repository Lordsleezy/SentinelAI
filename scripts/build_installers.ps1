# SentinelAI closed-beta installer build (Windows + Linux via WSL)
param(
    [string]$Version = "1.0.0-beta.1",
    [switch]$SkipLinux,
    [switch]$Publish
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

Write-Host "=== SentinelAI Installer Build v$Version ===" -ForegroundColor Cyan

& "$PSScriptRoot\generate_build_info.ps1" -BuildType beta -Version $Version

Write-Host "[1/6] Generating installer icons..." -ForegroundColor Yellow
python "$PSScriptRoot\generate_installer_icons.py"
if ($LASTEXITCODE -ne 0) { throw "Icon generation failed" }

Write-Host "[2/6] Validating icons..." -ForegroundColor Yellow
& "$PSScriptRoot\validate_installer.ps1" -IconOnly
if ($LASTEXITCODE -ne 0) { throw "Icon validation failed" }

Write-Host "[3/6] Building Python backend..." -ForegroundColor Yellow
$env:SENTINEL_NONINTERACTIVE = "1"
& "$PSScriptRoot\build_backend.bat"
if ($LASTEXITCODE -ne 0) { throw "Backend build failed" }

Write-Host "[4/6] Building Windows installer..." -ForegroundColor Yellow
Push-Location "$root\desktop-shell"
if (-not (Test-Path node_modules)) { npm install }
if ($Publish) {
  npm run dist:publish
} else {
  npm run dist
}
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "Windows electron-builder failed" }
Pop-Location

if (-not $SkipLinux) {
  Write-Host "[5/6] Building Linux installers (WSL)..." -ForegroundColor Yellow
  if (Test-Path "$root\scripts\build_linux_installers.sh") {
    $wslRoot = (wsl wslpath -a $root 2>$null)
    if (-not $wslRoot) {
      $drive = $root.Substring(0, 1).ToLower()
      $wslRoot = "/mnt/$drive" + ($root.Substring(2) -replace '\\', '/')
    }
    wsl bash -lc "cd '$wslRoot' && bash scripts/build_linux_installers.sh"
    if ($LASTEXITCODE -ne 0) {
      Write-Warning "Linux build failed - see WSL output. Windows artifact may still be usable."
    }
  }
} else {
  Write-Host '[5/6] Skipping Linux (-SkipLinux)' -ForegroundColor DarkGray
}

Write-Host "[6/6] Checksums + validation report..." -ForegroundColor Yellow
& "$PSScriptRoot\generate_installer_build_report.ps1" -Version $Version

Write-Host "=== Build complete ===" -ForegroundColor Green
Get-ChildItem "$root\installer_dist" -ErrorAction SilentlyContinue | Format-Table Name, Length, LastWriteTime
