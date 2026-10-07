# Extend Walmart in snapshot 2 between panel visits (owner-approved 2026-10-06;
# DECISIONS #57). The normal snapshot runner visits the next anchors in balanced-prefix
# order (stores already collected are skipped), at >= 5 s, stopping at the first block.
# A hard stop before the next panel visit keeps one Walmart process at a time.
#   Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File scripts\run_walmart_extend.ps1 -Deadline 2026-10-07T07:40" -WindowStyle Hidden
param([datetime]$Deadline, [int]$Budget = 2400)
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$log = Join-Path $root "data\raw\logs\walmart_extend.log"
function Note([string]$msg) { Add-Content $log "$(Get-Date -Format s) $msg" }
$ts = Get-Date -Format "yyyyMMdd_HHmm"
foreach ($e in "log", "err") { $f = "data\raw\logs\snap2_walmart.$e"; if (Test-Path $f) { Rename-Item $f "snap2_walmart_$ts.$e" } }
Note "start (budget $Budget, hard stop $($Deadline.ToString('s')))"
& "$root\scripts\run_snapshot_parallel.ps1" -SnapshotId 2 -Chains "walmart" -ExtraArgs "--budget $Budget" | Out-Null
Start-Sleep -Seconds 10
while ($true) {
    $p = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "collectors.snapshot" -and $_.CommandLine -match "walmart" }
    if (-not $p) { Note "finished"; break }
    if ((Get-Date) -ge $Deadline) { foreach ($x in $p) { Stop-Process -Id $x.ProcessId -Force }; Note "hard stop"; break }
    Start-Sleep -Seconds 30
}
