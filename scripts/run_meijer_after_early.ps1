# One-off: Meijer 'after' pass moved from Wed 12:00 to Wed 07:00 (owner away with the
# laptop from 09:10; pre-registration Addendum 9). Same 15 stores and items; hard stop
# 09:05.
param([datetime]$At = [datetime]"2026-10-07T07:00", [datetime]$Stop = [datetime]"2026-10-07T09:05",
      [string]$Python = "$env:USERPROFILE\.venvs\groceryStatistics\Scripts\python.exe")
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"; $env:PYTHONUNBUFFERED = "1"; $env:PYTHONPATH = $root
$log = Join-Path $root "data\raw\logs\meijer_event.log"
function Note([string]$msg) { Add-Content $log "$(Get-Date -Format s) $msg" }
Note "after (moved to 07:00, Addendum 9) : waiting until $($At.ToString('s'))"
while ((Get-Date) -lt $At) { Start-Sleep -Seconds 60 }
if ((Get-Date) -ge $Stop) { Note "after (07:00) : window missed"; exit }
$out = Join-Path $root "data\raw\logs\meijer_event_after.log"
Note "after : start"
$p = Start-Process -FilePath $Python -ArgumentList @("-m", "scripts.meijer_sample", "event", "--note", "meijer", "event", "after") `
    -NoNewWindow -PassThru -RedirectStandardOutput $out -RedirectStandardError "$out.err"
while (-not $p.HasExited) {
    if ((Get-Date) -ge $Stop) { Stop-Process -Id $p.Id -Force; Note "after : hard stop"; break }
    Start-Sleep -Seconds 30
}
Note "after : finished"
