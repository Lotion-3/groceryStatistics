# One-off rerun of the Kroger event CONTROL pass (pre-registration Addendum 3).
# The scheduled control pass (Mon Oct 5 10:00) failed at start: Start-Process split
# the multi-word --note into separate arguments. This reruns it at once, with a
# hard stop at Tue Oct 6 10:45 so it never overlaps the 11:00 "before" pass
# (one Kroger process at a time; the pacer is per process).
param([string]$Python = "$env:USERPROFILE\.venvs\groceryStatistics\Scripts\python.exe")
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"; $env:PYTHONUNBUFFERED = "1"; $env:PYTHONPATH = $root
$env:KROGER_BASE_URL = "https://api.kroger.com/v1"
$log = Join-Path $root "data\raw\logs\kroger_event.log"
$out = Join-Path $root "data\raw\logs\kroger_event_control_rerun.log"
$deadline = [datetime]"2026-10-06T10:45"
Add-Content $log "$(Get-Date -Format s) control pass (rerun, Addendum 3) : start"
$p = Start-Process -FilePath $Python -ArgumentList @("-m", "scripts.kroger_panel", "run", "--note", "kroger event control") `
    -NoNewWindow -PassThru -RedirectStandardOutput $out -RedirectStandardError "$out.err"
while (-not $p.HasExited) {
    if ((Get-Date) -ge $deadline) {
        Stop-Process -Id $p.Id -Force
        Add-Content $log "$(Get-Date -Format s) control pass (rerun) : hard stop at $($deadline.ToString('s'))"
        break
    }
    Start-Sleep -Seconds 30
}
Add-Content $log "$(Get-Date -Format s) control pass (rerun, Addendum 3) : finished"
