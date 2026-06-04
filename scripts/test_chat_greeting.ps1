# Launch SentinelAI, wait for backend, send "hi" until a non-error greeting returns.
$ErrorActionPreference = "Stop"

Get-Process SentinelAI, sentinel_backend -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep 3

$exe = $null
foreach ($sub in @("installer_dist6", "installer_dist5", "installer_dist4", "installer_dist3", "installer_dist2", "installer_dist")) {
    $c = Join-Path $PSScriptRoot "..\$sub\win-unpacked\SentinelAI.exe"
    if (Test-Path $c) { $exe = $c; break }
}
if (-not $exe) { throw "SentinelAI.exe not found - build installer first" }

$userData = Join-Path $env:APPDATA "SentinelAI"
Write-Host "Launching $exe"
$p = Start-Process -FilePath $exe -PassThru

function Get-AuthToken {
    $envPath = Join-Path $userData ".env"
    if (-not (Test-Path $envPath)) { return $null }
    foreach ($line in Get-Content $envPath) {
        if ($line -match '^SENTINELAI_AUTH_TOKEN=(.+)$') { return $Matches[1].Trim() }
    }
    return $null
}

$pingOk = $false
$deadline = (Get-Date).AddMinutes(4)
while ((Get-Date) -lt $deadline) {
    if ($p.HasExited) { throw "SentinelAI exited before backend was ready (exit $($p.ExitCode))" }
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:5001/api/ping" -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $pingOk = $true; Write-Host "Backend ping OK"; break }
    } catch { }
    Start-Sleep 5
}
if (-not $pingOk) {
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    throw "Backend did not respond on :5001 within 4 minutes"
}

$token = Get-AuthToken
if (-not $token) { throw "SENTINELAI_AUTH_TOKEN not found in $userData\.env" }
if ($token -eq 'your_secure_random_token_here' -or $token.Length -lt 16) {
    throw "Weak SENTINELAI_AUTH_TOKEN in .env ($($token.Length) chars). Quit SentinelAI, delete $userData\.env, relaunch."
}
Write-Host "Using auth token from .env"

$greeted = $false
$deadline = (Get-Date).AddMinutes(3)
$attempt = 0
while ((Get-Date) -lt $deadline -and -not $greeted) {
    $attempt++
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:5001/api/chat" -Method POST `
            -Body '{"message":"hi"}' -ContentType "application/json" `
            -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 90
        $text = [string]$resp.response
        $err = [string]$resp.error
        Write-Host "Attempt $attempt status=$($resp.status) worker=$($resp.worker) response=$text"
        if ($resp.status -eq 'ok' -and $text -and -not $err) {
            if ($text -notmatch 'error|failed|unauthorized|401|402|503') {
                $greeted = $true
            }
        }
    } catch {
        Write-Host "Attempt $attempt failed: $($_.Exception.Message)"
    }
    if (-not $greeted) { Start-Sleep 8 }
}

Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
Get-Process SentinelAI, sentinel_backend -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

if (-not $greeted) { throw "No successful greeting from /api/chat" }
Write-Host "PASS - Sentinel greeted: $text"
exit 0
