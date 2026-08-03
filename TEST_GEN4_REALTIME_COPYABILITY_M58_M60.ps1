param(
    [string]$ProjectRoot = "C:\smartmoney-ai",
    [switch]$FullSuite
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $ProjectRoot
$python = ".\.venv\Scripts\python.exe"

& $python -m compileall `
    backend/app/models/gen4_copyability.py `
    backend/app/services/blockchain_parser_gen4_copyability_service.py `
    backend/app/services/gen4_copyability_runtime.py `
    backend/app/workers/gen4_copyability_worker.py `
    scripts/configure_gen4_copyability_helius_webhook.py `
    scripts/verify_gen4_copyability_m58_m60.py `
    alembic/versions/b6f8d2e4c731_add_gen4_realtime_copyability.py
if ($LASTEXITCODE -ne 0) { throw "compileall fallito." }

& $python -m pytest `
    tests/test_parser_gen4_profitability_m47.py `
    tests/test_gen4_forward_shadow_m52_m53.py `
    tests/test_gen4_forward_dashboard_frontend_m54_m55.py `
    tests/test_gen4_forward_feed_m56_m57.py `
    tests/test_gen4_forward_feed_frontend_m56_m57.py `
    tests/test_gen4_copyability_m58_m60.py `
    tests/test_gen4_copyability_frontend_m58_m60.py `
    -q
if ($LASTEXITCODE -ne 0) { throw "Test mirati M47-M60 falliti." }

if ($FullSuite) {
    & $python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Suite completa fallita." }
}

& $python scripts/verify_gen4_copyability_m58_m60.py
if ($LASTEXITCODE -ne 0) { throw "Verifier M58-M60 fallito." }

$current = & $python -m alembic current
if ($current -notmatch "b6f8d2e4c731") {
    throw "Database non alla head b6f8d2e4c731."
}

$automationLine = Get-Content .env -Encoding UTF8 |
    Where-Object { $_ -match '^\s*AUTOMATION_API_KEY\s*=' } |
    Select-Object -Last 1
$automationKey = ($automationLine -split '=', 2)[1].Trim().Trim('"').Trim("'")

$status = Invoke-RestMethod `
    -Uri "https://smartmoney-ai-production-0042.up.railway.app/integrity/parser-gen4-copyability/status?recent_limit=5" `
    -Headers @{ "X-Automation-Key" = $automationKey } `
    -TimeoutSec 30

if (-not $status.runtime_enabled -or -not $status.autostart -or -not $status.worker_running) {
    throw "Runtime/worker M58-M60 online non attivo."
}
if ($status.campaign.status -ne "ACTIVE") {
    throw "Campagna M58-M60 online non ACTIVE."
}
if ($status.campaign.frozen_wallets.Count -ne 2) {
    throw "Numero wallet congelati online non valido."
}
if ($status.campaign.webhook.status -ne "ACTIVE") {
    throw "Webhook M58-M60 online non ACTIVE."
}
if (
    $status.safety.signer_access -or
    $status.safety.signed_transactions -ne 0 -or
    $status.safety.submitted_transactions -ne 0 -or
    $status.safety.paper_orders_created -ne 0 -or
    $status.safety.live_orders_created -ne 0
) {
    throw "Guardie sicurezza M58-M60 non valide."
}

Write-Host "M58-M60 TEST LOCALE E ONLINE: OK" -ForegroundColor Green
Write-Host "Dashboard: https://smartmoney-frontend-production-0e99.up.railway.app/gen4-forward"
