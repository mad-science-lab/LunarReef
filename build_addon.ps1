# Version: V26.281.0251
# Stage the ApexLunar Home Assistant add-on into dist\apexlunar\ - a folder ready
# to copy to the HA machine's /addons share (\<ha-ip>\addons\apexlunar).
# Local add-ons build from their own folder only, so the Python package is
# copied in beside the Dockerfile.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$dist = Join-Path $root "dist\apexlunar"

if (Test-Path $dist) { Remove-Item -Recurse -Force $dist }
New-Item -ItemType Directory -Force $dist | Out-Null

foreach ($f in "config.yaml", "build.yaml", "Dockerfile", "README.md", "CHANGELOG.md") {
    Copy-Item (Join-Path $root "addon\$f") $dist
}
# run.sh must be LF-only with no BOM or the container won't start
$runsh = (Get-Content (Join-Path $root "addon\run.sh") -Raw) -replace "`r`n", "`n"
[System.IO.File]::WriteAllText((Join-Path $dist "run.sh"), $runsh, (New-Object System.Text.UTF8Encoding($false)))

Copy-Item (Join-Path $root "apexlunar") (Join-Path $dist "apexlunar") -Recurse
Get-ChildItem (Join-Path $dist "apexlunar") -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Copy-Item (Join-Path $root "config.example.json") $dist

Write-Host "Staged add-on at: $dist"
Write-Host "Next: copy it to \<ha-ip>\addons\apexlunar, then in HA: Settings > Add-ons > Add-on Store >"
Write-Host "three-dot menu > Check for updates, and install ApexLunar from 'Local add-ons'."
