# Validates SentinelAI installer artifacts and icon requirements
param(
    [string]$InstallerDir = "$PSScriptRoot\..\installer_dist",
    [switch]$IconOnly
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$report = @()
function Add-Check($name, $ok, $detail) {
    $script:report += [pscustomobject]@{ Check = $name; Ok = $ok; Detail = $detail }
}

$iconPath = Join-Path $root "desktop-shell\assets\icon.ico"
Add-Check "icon.ico exists" (Test-Path $iconPath) $iconPath

if (Test-Path $iconPath) {
    $out = python (Join-Path $PSScriptRoot "generate_installer_icons.py") --validate-only 2>&1
    $iconOk = ($LASTEXITCODE -eq 0)
    Add-Check "icon.ico 256x256 (electron-builder)" $iconOk (($out | Select-Object -Last 1).ToString())
}

$iconsDir = Join-Path $root "desktop-shell\assets\icons"
Add-Check "Linux icons directory" (Test-Path $iconsDir) $iconsDir
if (Test-Path $iconsDir) {
    $png256 = Test-Path (Join-Path $iconsDir "256x256.png")
    $png512 = Test-Path (Join-Path $iconsDir "512x512.png")
    Add-Check "Linux 256/512 PNG" ($png256 -and $png512) ""
}

if (-not $IconOnly) {
    $exe = Get-ChildItem -Path $InstallerDir -Filter "SentinelAISetup*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    Add-Check "Windows installer exists" ($null -ne $exe) ($(if ($exe) { $exe.FullName } else { "not found" }))

    if ($exe) {
        Add-Check "Windows size > 50MB" ($exe.Length -gt 50MB) ("$([math]::Round($exe.Length/1MB,1)) MB")
    }

    $appImage = Get-ChildItem -Path $InstallerDir -Filter "SentinelAI*.AppImage" -ErrorAction SilentlyContinue | Select-Object -First 1
    Add-Check "Linux AppImage exists" ($null -ne $appImage) ($(if ($appImage) { $appImage.Name } else { "not found (build via WSL)" }))

    $deb = Get-ChildItem -Path $InstallerDir -Filter "SentinelAI*.deb" -ErrorAction SilentlyContinue | Select-Object -First 1
    Add-Check "Linux deb exists" ($null -ne $deb) ($(if ($deb) { $deb.Name } else { "not found (build via WSL)" }))

    $yml = Get-ChildItem -Path $InstallerDir -Filter "latest.yml" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    Add-Check "latest.yml (electron-updater)" ($null -ne $yml) ($(if ($yml) { $yml.FullName } else { "use npm run dist:publish" }))

    $pkg = Get-Content (Join-Path $root "desktop-shell\package.json") -Raw | ConvertFrom-Json
    Add-Check "NSIS desktop shortcut" ($pkg.build.nsis.createDesktopShortcut -eq $true) ""
    Add-Check "NSIS run after finish" ($pkg.build.nsis.runAfterFinish -eq $true) ""
    Add-Check "electron-updater dep" ($null -ne $pkg.dependencies.'electron-updater') ""
    Add-Check "Artifact name SentinelAISetup" ($pkg.build.artifactName -like "SentinelAISetup*") $pkg.build.artifactName
}

$report | Format-Table -AutoSize
$fail = ($report | Where-Object { -not $_.Ok }).Count
if ($fail -gt 0) { exit 1 }
exit 0
