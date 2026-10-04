# Kroger pipeline around the scheduled promotion expiry (DECISIONS #51;
# supersedes the daily-panel part of run_kroger_banners.ps1, DECISIONS #49).
#
# 9,326 snapshot-2 promotions are scheduled to expire at 2026-10-07T03:59:59Z
# (Tue Oct 6, 11:59 pm Eastern; the same instant nationwide). The panel is timed
# around that instant. All times below are this machine's local time (Eastern).
#
#   banner sample   until Mon Oct 5 09:30 (hard stop; resumable, finished after the event)
#   control pass    Mon Oct 5 10:00   60 panel stores x all items (no scheduled expiry)
#   before pass     Tue Oct 6 11:00   same (hard stop 22:15)
#   probe pre       Tue Oct 6 22:30   204 store-item queries with a promo ending at the event
#   probe post      Wed Oct 7 00:15   same, just after the expiry
#   probe early     Wed Oct 7 05:00   same, after the usual overnight price batch
#   after pass      Wed Oct 7 10:00   60 stores x all items
#   late pass       Thu Oct 8 10:00   60 stores x all items
#   banner sample   resumes after the late pass
#
# One Kroger process at a time, official production API, >= 9 s per request
# (collectors/common.py): every calendar day stays under 10,000 calls.
# Each pass is a new snapshot whose note names the pass; record the ids under
# `event_snapshots` in config/analysis.yaml (Module H).
#   Start-Process powershell -ArgumentList "-File scripts\run_kroger_event.ps1" -WindowStyle Hidden
param([string]$Python = "$env:USERPROFILE\.venvs\groceryStatistics\Scripts\python.exe")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"; $env:PYTHONUNBUFFERED = "1"; $env:PYTHONPATH = $root
$env:KROGER_BASE_URL = "https://api.kroger.com/v1"
$log = Join-Path $root "data\raw\logs\kroger_event.log"

function Note([string]$msg) { Add-Content $log "$(Get-Date -Format s) $msg" }

function Wait-Until([datetime]$t, [string]$what) {
    if ((Get-Date) -ge $t) { Note "$what : scheduled $($t.ToString('s')) already passed, starting now"; return }
    Note "$what : waiting until $($t.ToString('s'))"
    while ((Get-Date) -lt $t) { Start-Sleep -Seconds 60 }
}

# Run one python step; stop it at $deadline if it is still running (all steps are resumable).
function Run-Step([string[]]$pyArgs, [datetime]$deadline, [string]$what) {
    Note "$what : start (python $($pyArgs -join ' '))"
    $out = Join-Path $root "data\raw\logs\kroger_event_$($what -replace '\W','_').log"
    $p = Start-Process -FilePath $Python -ArgumentList $pyArgs -NoNewWindow -PassThru `
        -RedirectStandardOutput $out -RedirectStandardError "$out.err"
    while (-not $p.HasExited) {
        if ((Get-Date) -ge $deadline) {
            Stop-Process -Id $p.Id -Force
            Note "$what : hard stop at $($deadline.ToString('s')) (resumable)"
            return
        }
        Start-Sleep -Seconds 30
    }
    Note "$what : finished (exit $($p.ExitCode))"
}

$far = [datetime]"2026-12-31"
while (-not (Select-String -Path "data\raw\logs\snap2_kroger.log" -Pattern "^Done\." -Quiet)) {
    Note "waiting for the snapshot-2 Kroger pass to finish"
    Start-Sleep -Seconds 300
}
$bannerStop = [datetime]"2026-10-05T09:30"
if (-not (Test-Path "data\processed\kroger_store_universe.csv") -or -not (Test-Path "config\kroger_banner_sample.csv")) {
    Run-Step @("-m", "scripts.kroger_banners", "enumerate") $bannerStop "banner enumerate"
    Run-Step @("-m", "scripts.kroger_banners", "select") $bannerStop "banner select"
}
if ((Get-Date) -lt $bannerStop -and (Test-Path "config\kroger_banner_sample.csv")) {
    Run-Step @("-m", "scripts.kroger_banners", "run") $bannerStop "banner run"
}

$plan = @(
    @{ what = "control pass"; at = "2026-10-05T10:00"; stop = "2026-10-06T10:45"; args = @("run", "--note", "kroger event control") },
    @{ what = "before pass";  at = "2026-10-06T11:00"; stop = "2026-10-06T22:15"; args = @("run", "--note", "kroger event before") },
    @{ what = "probe pre";    at = "2026-10-06T22:30"; stop = "2026-10-06T23:55"; args = @("probe", "--note", "kroger event probe pre") },
    @{ what = "probe post";   at = "2026-10-07T00:15"; stop = "2026-10-07T04:50"; args = @("probe", "--note", "kroger event probe post") },
    @{ what = "probe early";  at = "2026-10-07T05:00"; stop = "2026-10-07T09:50"; args = @("probe", "--note", "kroger event probe early") },
    @{ what = "after pass";   at = "2026-10-07T10:00"; stop = "2026-10-08T09:45"; args = @("run", "--note", "kroger event after") },
    @{ what = "late pass";    at = "2026-10-08T10:00"; stop = "2026-10-09T09:45"; args = @("run", "--note", "kroger event late") }
)
foreach ($s in $plan) {
    Wait-Until ([datetime]$s.at) $s.what
    if ((Get-Date) -ge [datetime]$s.stop) { Note "$($s.what) : window missed, skipped"; continue }
    Run-Step (@("-m", "scripts.kroger_panel") + $s.args) ([datetime]$s.stop) $s.what
}
Run-Step @("-m", "scripts.kroger_banners", "run") $far "banner run (resume)"
Note "pipeline finished"
