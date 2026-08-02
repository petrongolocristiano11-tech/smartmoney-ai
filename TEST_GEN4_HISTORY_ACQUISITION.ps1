$ErrorActionPreference = "Stop"
$project = "C:\smartmoney-ai"
$python = Join-Path $project ".venv\Scripts\python.exe"
Set-Location $project

& $python -m compileall `
    backend/app/services/candidate_history_service.py `
    backend/app/services/gen4_history_acquisition_service.py `
    scripts/run_gen4_history_acquisition.py `
    scripts/verify_gen4_history_acquisition_contract.py `
    tests/test_extended_candidate_history.py `
    tests/test_gen4_history_acquisition_m48.py
if ($LASTEXITCODE -ne 0) { throw "Compilazione M48 fallita" }

& $python -m pytest `
    tests/test_gen4_history_acquisition_m48.py `
    tests/test_extended_candidate_history.py `
    tests/test_extended_candidate_history_api.py `
    tests/test_parser_gen4_profitability_m47.py `
    tests/test_wallet_edges_schema_contract.py -q
if ($LASTEXITCODE -ne 0) { throw "Test mirati M48 falliti" }

& $python scripts/verify_gen4_history_acquisition_contract.py
if ($LASTEXITCODE -ne 0) { throw "Verifier M48 fallito" }

Write-Host "Test M48 V3 superati." -ForegroundColor Green
