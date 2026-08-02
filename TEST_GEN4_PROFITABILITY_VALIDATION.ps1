$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo = "C:\smartmoney-ai"
$python = Join-Path $repo ".venv\Scripts\python.exe"
$downloads = Join-Path $HOME "Downloads"
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$report = Join-Path $downloads "smartmoney-gen4-profitability-preview-$timestamp.json"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python virtual environment non trovato: $python"
}

Set-Location $repo

Write-Host "[1/7] Compilazione M47" -ForegroundColor Cyan
& $python -m compileall `
    backend/app/models/gen4_profitability.py `
    backend/app/services/blockchain_parser_gen4_profitability_service.py `
    backend/app/core/config.py `
    backend/app/schemas/blockchain_integrity.py `
    backend/app/main.py `
    alembic/versions/e3b5c8d1f297_add_gen4_walk_forward_profitability.py `
    scripts/verify_gen4_profitability_contract.py `
    scripts/test_gen4_profitability_postgresql_migration.py `
    scripts/run_gen4_profitability_preview.py `
    tests/test_parser_gen4_profitability_m47.py
if ($LASTEXITCODE -ne 0) { throw "Compilazione fallita" }

Write-Host "[2/7] Test mirati e regressioni" -ForegroundColor Cyan
& $python -m pytest `
    tests/test_parser_gen4_profitability_m47.py `
    tests/test_wallet_edges_schema_contract.py `
    tests/test_candidate_backtest_promotion_gate.py `
    tests/test_parser_unified_decision_m31.py `
    -q
if ($LASTEXITCODE -ne 0) { throw "Test mirati falliti" }

Write-Host "[3/7] Verifier statico e OpenAPI" -ForegroundColor Cyan
& $python scripts/verify_gen4_profitability_contract.py
if ($LASTEXITCODE -ne 0) { throw "Verifier M47 fallito" }

Write-Host "[4/7] Lifecycle Alembic PostgreSQL temporaneo" -ForegroundColor Cyan
& $python scripts/test_gen4_profitability_postgresql_migration.py
if ($LASTEXITCODE -ne 0) { throw "Lifecycle PostgreSQL M47 fallito" }

Write-Host "[5/7] Suite backend completa" -ForegroundColor Cyan
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Suite backend completa fallita" }

Write-Host "[6/7] Database corrente e preview read-only" -ForegroundColor Cyan
& $python scripts/verify_gen4_profitability_contract.py --current-database
if ($LASTEXITCODE -ne 0) { throw "Verifica database M47 fallita" }
& $python scripts/run_gen4_profitability_preview.py --output $report
if ($LASTEXITCODE -ne 0) { throw "Preview Gen4 fallita" }

Write-Host "[7/7] Stato Git" -ForegroundColor Cyan
git status --short

Write-Host "`nTEST M47 COMPLETO SUPERATO." -ForegroundColor Green
Write-Host "Report: $report" -ForegroundColor Green
Write-Host "Nessun commit, push, deploy o attivazione LIVE eseguito."
