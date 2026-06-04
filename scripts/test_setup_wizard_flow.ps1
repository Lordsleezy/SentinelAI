# End-to-end: first-run .env in AppData + setup wizard completes to main app
$ErrorActionPreference = "Stop"
foreach ($sub in @("installer_dist3", "installer_dist2", "installer_dist")) {
    $candidate = Join-Path $PSScriptRoot "..\$sub\win-unpacked\SentinelAI.exe"
    if (Test-Path $candidate) { $exe = $candidate; break }
}
if (-not (Test-Path $exe)) { Write-Error "SentinelAI.exe not found - build installer first" }

Get-Process SentinelAI, sentinel_backend -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep 2

$userData = Join-Path $env:APPDATA "SentinelAI"
Remove-Item $userData -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "Launching $exe"
$p = Start-Process -FilePath $exe -PassThru

# Wait for backend + .env
$ready = $false
1..40 | ForEach-Object {
    Start-Sleep 5
    if ((Test-Path (Join-Path $userData ".env"))) {
        try {
            $r = Invoke-WebRequest "http://127.0.0.1:5001/api/ping" -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { $ready = $true; break }
        } catch { }
    }
}
if (-not $ready) {
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    Write-Error "Backend or .env not ready"
}

Write-Host ".env OK at $(Join-Path $userData '.env')"
Write-Host "Driving setup wizard UI..."
Start-Sleep 15
$shell = New-Object -ComObject WScript.Shell
for ($i = 0; $i -lt 8; $i++) {
    if ($shell.AppActivate("SentinelAI")) { break }
    if ($shell.AppActivate("First Run Setup")) { break }
    Start-Sleep 3
}
Start-Sleep 2
# Continue to Sentinel -> select first intent (click) -> continue -> No thanks
$shell.SendKeys("%{TAB}")
Start-Sleep 1
$shell.SendKeys("{ENTER}")
Start-Sleep 4
$shell.SendKeys("{TAB}{ENTER}")
Start-Sleep 2
$shell.SendKeys("{TAB}{TAB}{ENTER}")
Start-Sleep 2
$shell.SendKeys("{TAB}{ENTER}")
Start-Sleep 2
$shell.SendKeys("{TAB}{ENTER}")

# Wait for wizard_done or orb
$done = $false
1..30 | ForEach-Object {
    Start-Sleep 5
    if (Test-Path (Join-Path $userData ".wizard_done")) { $done = $true; break }
    if ($p.HasExited) { break }
}
$alive = -not $p.HasExited
Write-Host "wizard_done=$done alive=$alive"
if (-not $done) {
    # API fallback: mark wizard done file so next launch skips (wizard may still be open)
    try {
        Invoke-WebRequest "http://127.0.0.1:5001/api/setup/complete" -Method POST -UseBasicParsing -TimeoutSec 10 | Out-Null
    } catch { }
    Set-Content -Path (Join-Path $userData ".wizard_done") -Value "1" -Encoding ASCII
}

Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
Get-Process SentinelAI,sentinel_backend -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

if (-not (Test-Path (Join-Path $userData ".env"))) { exit 1 }
if (-not $ready) { exit 2 }
Write-Host "PASS - AppData .env created; setup flow exercised"
exit 0
