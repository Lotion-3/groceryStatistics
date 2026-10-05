# Ask Windows not to idle-sleep while data collection runs (no settings changed).
# Uses SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED): the request lasts
# only while this process runs, and stopping the process (or the -Until time) restores
# normal behaviour. It does not override closing the lid or a manual sleep.
#   Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File scripts\keep_awake.ps1" -WindowStyle Hidden
param([datetime]$Until = [datetime]"2026-10-08T15:00")
Add-Type -Namespace Win32 -Name Power -MemberDefinition @'
[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);
'@
$ES_CONTINUOUS = [uint32]"0x80000000"; $ES_SYSTEM_REQUIRED = [uint32]"0x00000001"
$log = Join-Path (Split-Path -Parent $PSScriptRoot) "data\raw\logs\keep_awake.log"
Add-Content $log "$(Get-Date -Format s) keep-awake on until $($Until.ToString('s')) (pid $PID)"
while ((Get-Date) -lt $Until) {
    [void][Win32.Power]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED)
    Start-Sleep -Seconds 60
}
[void][Win32.Power]::SetThreadExecutionState($ES_CONTINUOUS)
Add-Content $log "$(Get-Date -Format s) keep-awake off"
