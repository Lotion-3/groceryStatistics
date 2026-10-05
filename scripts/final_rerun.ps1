# Final analysis rerun, after the Kroger late pass (Thu Oct 8) and the banner sample.
# Runs detached-safe steps in order and logs to data/raw/logs/final_rerun.log:
#   1. run_all.py (coverage, Modules A-I; Module B at 2,000 draws)
#   2. zone robustness for Kroger and Meijer (split-half and prior)
# Kroger zones/timing in the write-up are then updated from the tables. The frozen
# pre-registered zones (config/prereg_kroger_zones.csv) are untouched; Module H uses them.
#   Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File scripts\final_rerun.ps1" -WindowStyle Hidden
param([string]$Python = "$env:USERPROFILE\.venvs\groceryStatistics\Scripts\python.exe")
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"; $env:PYTHONUNBUFFERED = "1"; $env:PYTHONPATH = $root
$env:GS_MODB_DRAWS = "2000"; $env:GS_MODB_TUNE = "1500"
$log = Join-Path $root "data\raw\logs\final_rerun.log"
function Note([string]$msg) { Add-Content $log "$(Get-Date -Format s) $msg" }
Note "run_all : start"
& $Python run_all.py *>> $log
Note "run_all : finished"
Note "zone sensitivity (kroger, meijer) : start"
& $Python -m analysis.zone_sensitivity --chains "kroger,meijer" *>> $log
Note "zone sensitivity : finished"
Note "final rerun finished"
