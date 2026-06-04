# Writes INSTALLER_BUILD_REPORT.md with PASS/WARNING/FAIL and checksums
param([string]$Version = "1.0.0-beta.1")

$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
$dist = Join-Path $root "installer_dist"
$results = @()

function Add-Result($name, $status, $detail) {
    $script:results += [pscustomobject]@{ Check = $name; Status = $status; Detail = $detail }
}

function Get-Sha256($path) {
    if (-not (Test-Path $path)) { return "" }
    return (Get-FileHash -Path $path -Algorithm SHA256).Hash.ToLower()
}

# Icon
$icon = Join-Path $root "desktop-shell\assets\icon.ico"
if (Test-Path $icon) {
    $py = python "$PSScriptRoot\generate_installer_icons.py" 2>&1
    if ($LASTEXITCODE -eq 0) { Add-Result "Icon ICO 256+" "PASS" ($py | Select-Object -Last 1) }
    else { Add-Result "Icon ICO 256+" "FAIL" ($py -join " ") }
} else { Add-Result "Icon ICO 256+" "FAIL" "missing" }

# Windows
$win = Get-ChildItem $dist -Filter "SentinelAISetup*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($win) {
    Add-Result "Windows SentinelAISetup.exe" "PASS" "$([math]::Round($win.Length/1MB,2)) MB — $(Get-Sha256 $win.FullName)"
} else {
    Add-Result "Windows SentinelAISetup.exe" "FAIL" "not built"
}

# Linux
$app = Get-ChildItem $dist -Filter "*.AppImage" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($app) {
    Add-Result "Linux AppImage" "PASS" "$($app.Name) $([math]::Round($app.Length/1MB,2)) MB"
} else {
    Add-Result "Linux AppImage" "WARNING" "Build with WSL: scripts/build_linux_installers.sh"
}

$deb = Get-ChildItem $dist -Filter "*.deb" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($deb) {
    Add-Result "Linux deb" "PASS" "$($deb.Name) $([math]::Round($deb.Length/1MB,2)) MB"
} else {
    Add-Result "Linux deb" "WARNING" "Build with WSL"
}

$yml = Get-ChildItem $dist -Filter "latest.yml" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if ($yml) { Add-Result "electron-updater latest.yml" "PASS" $yml.FullName }
else { Add-Result "electron-updater latest.yml" "WARNING" "Run npm run dist:publish for auto-update feed" }

try {
    python "$PSScriptRoot\validate_updater.py" 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { Add-Result "Updater validation script" "PASS" "validate_updater.py" }
    else { Add-Result "Updater validation script" "WARNING" "exit $LASTEXITCODE" }
} catch {
    Add-Result "Updater validation script" "WARNING" $_.Exception.Message
}

$lines = @(
    "# Installer Build Report",
    "",
    "**Version:** $Version",
    "**Generated:** $((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))",
    "",
    "## Results",
    "",
    "| Check | Status | Detail |",
    "|-------|--------|--------|",
)
foreach ($r in $results) {
    $d = ($r.Detail -replace '\|', '/')
    $lines += "| $($r.Check) | $($r.Status) | $d |"
}
$fails = ($results | Where-Object { $_.Status -eq "FAIL" }).Count
$warns = ($results | Where-Object { $_.Status -eq "WARNING" }).Count
$lines += ""
$lines += "**Summary:** $($results.Count) checks, $fails FAIL, $warns WARNING"
$lines += ""
$lines += "## Artifact paths"
$lines += ""
$lines += "| Platform | Path |"
$lines += "|----------|------|"
if ($win) {
    $lines += "| Windows | ``installer_dist/$($win.Name)`` |"
    $lines += "| SHA-256 | ``$(Get-Sha256 $win.FullName)`` |"
}
if ($app) { $lines += "| Linux AppImage | ``installer_dist/$($app.Name)`` |" }
if ($deb) { $lines += "| Linux deb | ``installer_dist/$($deb.Name)`` |" }
$lines += ""
$lines += "## GitHub Release upload"
$lines += ""
$lines += "1. Tag ``v$Version``"
$lines += "2. Upload ``SentinelAISetup.exe`` (+ ``latest.yml`` and ``*.blockmap`` if using ``dist:publish``)"
$lines += "3. Upload Linux ``SentinelAI.AppImage`` and ``SentinelAI.deb``"
$lines += "4. Paste SHA-256 into release notes for Python updater fallback"
$lines += ""

$outPath = Join-Path $root "INSTALLER_BUILD_REPORT.md"
$lines -join "`n" | Set-Content -Path $outPath -Encoding UTF8
Write-Host "Wrote $outPath"
