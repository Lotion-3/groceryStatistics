# Run one snapshot with one background process per chain (DECISIONS #25).
# Each chain is a different domain and keeps its own pacing (<= 1 request / 2 s),
# so running them side by side does not raise the rate at any retailer.
# All three processes write to the same snapshot id; the DB uses WAL mode.
#
#   .\scripts\run_snapshot_parallel.ps1 -Notes "snapshot 1 (main)"
#   .\scripts\run_snapshot_parallel.ps1 -SnapshotId 2     # resume
#
# THIS GENERATES RETAILER TRAFFIC. Owner approval required.
param(
    [string]$Notes = "",
    [int]$SnapshotId = 0,
    [string]$Chains = "target,walmart,costco",
    [string]$ExtraArgs = "",
    [string]$Python = "$env:USERPROFILE\.venvs\groceryStatistics\Scripts\python.exe"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONUNBUFFERED = "1"
if ($SnapshotId -eq 0) {
    $SnapshotId = [int](& $Python -m collectors.snapshot --new-snapshot-only --notes $Notes | Select-Object -Last 1)
}
$logs = Join-Path $root "data\raw\logs"
New-Item -ItemType Directory -Force $logs | Out-Null
Write-Host "Snapshot $SnapshotId"
foreach ($c in $Chains.Split(",")) {
    $log = Join-Path $logs "snap${SnapshotId}_$c.log"
    $args = @("-m", "collectors.snapshot", "--snapshot-id", "$SnapshotId", "--chains", $c) + ($ExtraArgs.Split(" ", [System.StringSplitOptions]::RemoveEmptyEntries))
    Start-Process -FilePath $Python -ArgumentList $args -RedirectStandardOutput $log `
        -RedirectStandardError "$log.err" -NoNewWindow -PassThru | ForEach-Object { Write-Host "  $c -> pid $($_.Id), log $log" }
}
