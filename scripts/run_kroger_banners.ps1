# Kroger pipeline (DECISIONS #49; owner-approved order: banner sample, then
# daily panel). Waits until the running snapshot-2 Kroger pass has finished (so
# only one process uses the Kroger API at a time), then: enumerate -> select ->
# run the banner sample, then 3 Kroger daily-panel days ~24 h apart (each a new
# snapshot; record their ids under panel_snapshots in config/analysis.yaml).
# Official production API only.
#   Start-Process powershell -ArgumentList "-File scripts\run_kroger_banners.ps1" -WindowStyle Hidden
param([string]$Python = "$env:USERPROFILE\.venvs\groceryStatistics\Scripts\python.exe")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"; $env:PYTHONUNBUFFERED = "1"; $env:PYTHONPATH = $root
$env:KROGER_BASE_URL = "https://api.kroger.com/v1"
$log = Join-Path $root "data\raw\logs\kroger_banners.log"
while (-not (Select-String -Path "data\raw\logs\snap2_kroger.log" -Pattern "^Done\." -Quiet)) {
    Add-Content $log "$(Get-Date -Format s) waiting for the snapshot-2 Kroger pass to finish"
    Start-Sleep -Seconds 300
}
foreach ($step in "enumerate", "select", "run") {
    Add-Content $log "$(Get-Date -Format s) step: $step"
    & $Python -m scripts.kroger_banners $step *>> $log
}
for ($day = 1; $day -le 3; $day++) {
    $start = Get-Date
    Add-Content $log "$(Get-Date -Format s) kroger panel day $day"
    & $Python -m scripts.kroger_panel run *>> $log
    if ($day -lt 3) {
        $next = $start.AddHours(24)
        while ((Get-Date) -lt $next) { Start-Sleep -Seconds 600 }
    }
}
Add-Content $log "$(Get-Date -Format s) pipeline finished"
