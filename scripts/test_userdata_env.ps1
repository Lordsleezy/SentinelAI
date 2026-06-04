# Quick validation: .env is created under AppData, not Program Files
$ErrorActionPreference = "Stop"
$userData = Join-Path $env:APPDATA "SentinelAI"
$exe = Join-Path $PSScriptRoot "..\installer_dist\win-unpacked\SentinelAI.exe"
if (-not (Test-Path $exe)) {
    Write-Error "Build win-unpacked first: $exe"
}

Write-Host "Cleaning $userData ..."
Remove-Item $userData -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "Launching SentinelAI (packaged)..."
$p = Start-Process -FilePath $exe -PassThru -WindowStyle Normal

$deadline = (Get-Date).AddMinutes(3)
$envOk = $false
$pingOk = $false
while ((Get-Date) -lt $deadline) {
    if ((Test-Path (Join-Path $userData ".env"))) { $envOk = $true }
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:5001/api/ping" -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $pingOk = $true }
    } catch { }
    if ($envOk -and $pingOk) { break }
    Start-Sleep -Seconds 5
}

Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
Get-Process -Name "SentinelAI","sentinel_backend" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host "userData .env exists: $envOk ($(Join-Path $userData '.env'))"
Write-Host "backend /api/ping: $pingOk"
if (-not $envOk) { exit 1 }
if (-not $pingOk) { exit 2 }
Write-Host "PASS"
exit 0
