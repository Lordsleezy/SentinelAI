# Stage Godot 4.x win64 for Sentinel installer (tools/godot + installer_assets/godot_runtime)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$rel = Invoke-RestMethod -Uri "https://api.github.com/repos/godotengine/godot/releases/latest"
$asset = $rel.assets | Where-Object { $_.name -match 'win64.*\.zip$' } | Select-Object -First 1
if (-not $asset) { throw "No win64 zip in latest Godot release" }

$zipName = $asset.name
$urls = @(
    (Join-Path $Root "installer_assets\godot_runtime"),
    (Join-Path $Root "tools\godot")
)
foreach ($dir in $urls) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $zipPath = Join-Path $dir $zipName
    Write-Host "Downloading to $zipPath"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath -UseBasicParsing
    Expand-Archive -Path $zipPath -DestinationPath $dir -Force
    $exe = Get-ChildItem -Path $dir -Recurse -Filter "Godot*.exe" | Select-Object -First 1
    if ($exe) {
        Copy-Item $exe.FullName (Join-Path $dir $exe.Name) -Force
        Write-Host "  OK $($exe.Name) in $dir"
    }
}

Write-Host "Godot runtime staged."
