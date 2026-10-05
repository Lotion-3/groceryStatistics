# Walmart repeat-visit panel (owner-approved 2026-10-04; DECISIONS #52).
# 10 stores x 17 confirmed items, at 08:00, 14:00 and 20:00 Eastern (this machine's
# local time) from Mon Oct 5 to Thu Oct 8, around the Kroger promotion expiry
# (Tue Oct 6, 23:59 ET). Each visit is a new snapshot ("walmart panel <time>"),
# hard-stopped after 1 h 45 min. A block stops the visit; the chain's pause
# policy (collectors/session_stash.py) then skips later visits while it lasts.
#   Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File scripts\run_walmart_panel.ps1" -WindowStyle Hidden
param([string]$Python = "$env:USERPROFILE\.venvs\groceryStatistics\Scripts\python.exe")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"; $env:PYTHONUNBUFFERED = "1"; $env:PYTHONPATH = $root
$log = Join-Path $root "data\raw\logs\walmart_panel.log"
function Note([string]$msg) { Add-Content $log "$(Get-Date -Format s) $msg" }

$times = @()
foreach ($d in "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08") {
    foreach ($h in "08:00", "14:00", "20:00") { $times += [datetime]"$($d)T$h" }
}
$times = $times | Where-Object { $_ -le [datetime]"2026-10-08T14:00" }

foreach ($t in $times) {
    $stop = $t.AddMinutes(105)
    if ((Get-Date) -ge $stop) { Note "visit $($t.ToString('s')): window missed, skipped"; continue }
    if ((Get-Date) -lt $t) {
        Note "visit $($t.ToString('s')): waiting"
        while ((Get-Date) -lt $t) { Start-Sleep -Seconds 60 }
    }
    $out = Join-Path $root ("data\raw\logs\walmart_panel_" + $t.ToString("MMdd_HHmm") + ".log")
    Note "visit $($t.ToString('s')): start"
    $p = Start-Process -FilePath $Python -ArgumentList @("-m", "scripts.walmart_panel", "visit") -NoNewWindow -PassThru `
        -RedirectStandardOutput $out -RedirectStandardError "$out.err"
    while (-not $p.HasExited) {
        if ((Get-Date) -ge $stop) { Stop-Process -Id $p.Id -Force; Note "visit $($t.ToString('s')): hard stop"; break }
        Start-Sleep -Seconds 30
    }
    Note "visit $($t.ToString('s')): finished"
}
Note "walmart panel finished"
