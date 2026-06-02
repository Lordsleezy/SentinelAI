# Stage ProjectDiscovery Guardian Core tools for Sentinel installer + bundled tools/
# Run from repo root: .\scripts\stage_guardian_core.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Assets = Join-Path $Root "installer_assets\guardian_core"
$Tools = Join-Path $Root "tools"

$ToolsSpec = @(
    @{ Id = "httpx";     Zip = "httpx_windows_amd64.zip" },
    @{ Id = "subfinder"; Zip = "subfinder_windows_amd64.zip" },
    @{ Id = "katana";    Zip = "katana_windows_amd64.zip" },
    @{ Id = "nuclei";    Zip = "nuclei_windows_amd64.zip" }
)

function Get-LatestAssetUrl($Repo, $ZipName) {
    $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" -Headers @{ "User-Agent" = "SentinelAI" }
    $asset = $rel.assets | Where-Object { $_.name -eq $ZipName } | Select-Object -First 1
    if (-not $asset) {
        $asset = $rel.assets | Where-Object { $_.name -like "${Repo}_*_windows_amd64.zip" } | Select-Object -First 1
    }
    if (-not $asset) { throw "No windows_amd64 zip in $Repo latest release" }
    return @{ Url = $asset.browser_download_url; Name = $asset.name }
}

foreach ($t in $ToolsSpec) {
    $id = $t.Id
    $zipName = $t.Zip
    $repo = "projectdiscovery/$id"
    $assetDir = Join-Path $Assets $id
    $toolDir = Join-Path $Tools $id
    New-Item -ItemType Directory -Force -Path $assetDir, $toolDir | Out-Null

    $asset = Get-LatestAssetUrl $repo $zipName
    $zipPath = Join-Path $assetDir $asset.Name
    Write-Host "Downloading $id from $($asset.Url)"
    Invoke-WebRequest -Uri $asset.Url -OutFile $zipPath -UseBasicParsing

    $exeName = "$id.exe"
    Expand-Archive -Path $zipPath -DestinationPath $toolDir -Force
    $found = Get-ChildItem -Path $toolDir -Recurse -Filter $exeName | Select-Object -First 1
    if ($found) {
        Copy-Item $found.FullName (Join-Path $toolDir $exeName) -Force
        Copy-Item $found.FullName (Join-Path $assetDir $exeName) -Force
        Write-Host "  OK $id -> tools\$id\$exeName"
    } else {
        Write-Warning "  $exeName not found after extract for $id"
    }
}

Write-Host ""
Write-Host "Guardian Core staged. Rebuild installer to bundle installer_assets/guardian_core and tools/."
