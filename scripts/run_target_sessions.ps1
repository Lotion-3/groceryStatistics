# Target budgeted sessions on a fixed cadence (owner-approved 2026-10-06; DECISIONS #57).
# One 64-query run every 6 h (16 matched items, snapshot 2), under the unchanged session
# policy (DECISIONS #44-47): a fresh session per run, replaced only after a refusal (at
# most twice per run), a daily cap of 8 fresh sessions, and the escalating pause after a
# counted block. Four runs a day keep within the cap. A run is skipped if the previous
# one is still going or a pause is active (the runner checks the pause itself).
#   Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File scripts\run_target_sessions.ps1" -WindowStyle Hidden
param([datetime]$Until = [datetime]"2026-10-08T22:00")
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$log = Join-Path $root "data\raw\logs\target_sessions.log"
function Note([string]$msg) { Add-Content $log "$(Get-Date -Format s) $msg" }
$items = "cer_honeynut_cheerios_15_4,pas_barilla_spaghetti_16,pas_prego_traditional_24,pas_raos_marinara_24,can_campbells_chicken_noodle_10_75,can_delmonte_green_beans_14_5,can_swanson_chicken_broth_32,sod_coke_12pk,sod_pepsi_12pk,snk_oreo_13_29,cnd_hellmanns_mayo_30,cnd_jif_creamy_16,cnd_smuckers_strawberry_18,bev_lipton_black_tea_100ct,pc_listerine_cool_mint_1l,otc_zyrtec_10mg_30"
$next = Get-Date
while ($next -lt $Until) {
    while ((Get-Date) -lt $next) { Start-Sleep -Seconds 60 }
    $busy = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "collectors.snapshot" -and $_.CommandLine -match "target" }
    if ($busy) { Note "previous Target run still active; skipped" }
    else {
        $ts = Get-Date -Format "yyyyMMdd_HHmm"
        foreach ($e in "log", "err") { $f = "data\raw\logs\snap2_target.$e"; if (Test-Path $f) { Rename-Item $f "snap2_target_$ts.$e" } }
        Note "run start"
        & "$root\scripts\run_snapshot_parallel.ps1" -SnapshotId 2 -Chains "target" -ExtraArgs "--budget 64 --items $items" | Out-Null
    }
    $next = $next.AddHours(6)
}
Note "target sessions finished"
