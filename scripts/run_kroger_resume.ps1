# Resume a Kroger event pass in an existing snapshot (resumable: pairs already collected
# are skipped), with a hard stop. Used to restart the 'before' pass at 1 request/s
# (DECISIONS #55) without creating a second snapshot.
#   Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File scripts\run_kroger_resume.ps1 -SnapshotId 10 -Pass before -Deadline 2026-10-06T22:15" -WindowStyle Hidden
param([int]$SnapshotId, [string]$Pass, [datetime]$Deadline,
      [string]$Python = "$env:USERPROFILE\.venvs\groceryStatistics\Scripts\python.exe")
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"; $env:PYTHONUNBUFFERED = "1"; $env:PYTHONPATH = $root
$env:KROGER_BASE_URL = "https://api.kroger.com/v1"
$log = Join-Path $root "data\raw\logs\kroger_event.log"
$out = Join-Path $root "data\raw\logs\kroger_event_$($Pass)_resume.log"
Add-Content $log "$(Get-Date -Format s) $Pass pass (resume at 1 req/s, snapshot $SnapshotId) : start"
$p = Start-Process -FilePath $Python -ArgumentList @("-m", "scripts.kroger_panel", "run", "--snapshot-id", "$SnapshotId", "--note", "kroger", "event", $Pass) `
    -NoNewWindow -PassThru -RedirectStandardOutput $out -RedirectStandardError "$out.err"
while (-not $p.HasExited) {
    if ((Get-Date) -ge $Deadline) { Stop-Process -Id $p.Id -Force; Add-Content $log "$(Get-Date -Format s) $Pass pass (resume) : hard stop"; break }
    Start-Sleep -Seconds 20
}
Add-Content $log "$(Get-Date -Format s) $Pass pass (resume, snapshot $SnapshotId) : finished"
