# Meijer event passes (owner-approved 2026-10-05; DECISIONS #53). 15 Meijer stores x
# all items via Constructor.io search (no store-locator use), each pass a new
# snapshot. Meijer sale prices end on Tue Oct 6 (the same night as the Kroger
# expiry): control (Mon night), before (Tue 18:00), after (Wed 12:00).
#   Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File scripts\run_meijer_event.ps1" -WindowStyle Hidden
param([string]$Python = "$env:USERPROFILE\.venvs\groceryStatistics\Scripts\python.exe")
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"; $env:PYTHONUNBUFFERED = "1"; $env:PYTHONPATH = $root
$log = Join-Path $root "data\raw\logs\meijer_event.log"
function Note([string]$msg) { Add-Content $log "$(Get-Date -Format s) $msg" }
$plan = @(
    @{ what = "control"; at = "2026-10-05T19:30"; stop = "2026-10-05T23:30" },
    @{ what = "before";  at = "2026-10-06T18:00"; stop = "2026-10-06T22:30" },
    @{ what = "after";   at = "2026-10-07T12:00"; stop = "2026-10-07T16:30" }
)
foreach ($s in $plan) {
    $t = [datetime]$s.at; $stop = [datetime]$s.stop
    if ((Get-Date) -ge $stop) { Note "$($s.what) : window missed, skipped"; continue }
    if ((Get-Date) -lt $t) { Note "$($s.what) : waiting until $($t.ToString('s'))"; while ((Get-Date) -lt $t) { Start-Sleep -Seconds 60 } }
    $out = Join-Path $root "data\raw\logs\meijer_event_$($s.what).log"
    Note "$($s.what) : start"
    $p = Start-Process -FilePath $Python -ArgumentList @("-m", "scripts.meijer_sample", "event", "--note", "meijer", "event", $s.what) `
        -NoNewWindow -PassThru -RedirectStandardOutput $out -RedirectStandardError "$out.err"
    while (-not $p.HasExited) {
        if ((Get-Date) -ge $stop) { Stop-Process -Id $p.Id -Force; Note "$($s.what) : hard stop"; break }
        Start-Sleep -Seconds 30
    }
    Note "$($s.what) : finished"
}
Note "meijer event passes finished"
