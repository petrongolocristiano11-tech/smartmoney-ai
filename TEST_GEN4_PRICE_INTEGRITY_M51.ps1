$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo = "C:\smartmoney-ai"
$python = Join-Path $repo ".venv\Scripts\python.exe"
$downloads = Join-Path $HOME "Downloads"
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$report = Join-Path $downloads "smartmoney-gen4-price-integrity-m51-$timestamp.json"

Set-Location $repo

Write-Host "[1/6] Compilazione M51" -ForegroundColor Cyan
& $python -m compileall `
    backend/app/core/constants.py `
    backend/app/core/config.py `
    backend/app/services/blockchain_parser_gen4_profitability_service.py `
    scripts/verify_gen4_price_integrity_m51.py `
    scripts/run_gen4_price_integrity_preview.py `
    tests/test_gen4_price_integrity_m51.py
if ($LASTEXITCODE -ne 0) { throw "Compilazione M51 fallita" }

Write-Host "[2/6] Test mirati M47-M51" -ForegroundColor Cyan
& $python -m pytest `
    tests/test_gen4_price_integrity_m51.py `
    tests/test_parser_gen4_profitability_m47.py `
    tests/test_gen4_history_acquisition_m48.py `
    tests/test_gen4_evidence_sprint_m49_m50.py `
    -q
if ($LASTEXITCODE -ne 0) { throw "Test mirati M51 falliti" }

Write-Host "[3/6] Verifier statico e OpenAPI" -ForegroundColor Cyan
& $python scripts/verify_gen4_price_integrity_m51.py
if ($LASTEXITCODE -ne 0) { throw "Verifier M51 fallito" }

Write-Host "[4/6] Suite backend completa" -ForegroundColor Cyan
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Suite backend completa fallita" }

Write-Host "[5/6] Database e ricalcolo read-only" -ForegroundColor Cyan
& $python scripts/verify_gen4_price_integrity_m51.py --current-database
if ($LASTEXITCODE -ne 0) { throw "Verifica database M51 fallita" }
& $python scripts/run_gen4_price_integrity_preview.py --output $report
if ($LASTEXITCODE -ne 0) { throw "Ricalcolo M51 fallito" }

Write-Host "[6/6] Git" -ForegroundColor Cyan
git diff --check
if ($LASTEXITCODE -ne 0) { throw "git diff --check ha trovato errori" }
git status --short

Write-Host "`nTEST M51 COMPLETO SUPERATO." -ForegroundColor Green
Write-Host "Report: $report" -ForegroundColor Green
Write-Host "Nessun Helius, scrittura DB, promozione, paper o LIVE."
