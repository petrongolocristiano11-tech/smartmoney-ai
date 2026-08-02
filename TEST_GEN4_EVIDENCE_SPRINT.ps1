$ErrorActionPreference = "Stop"
$project = "C:\smartmoney-ai"
$python = Join-Path $project ".venv\Scripts\python.exe"
$expectedHead = "e3b5c8d1f297"

Set-Location $project
if (-not (Test-Path -LiteralPath $python)) { throw "Virtual environment non trovato" }

Write-Host "[1/4] Compilazione M49-M50" -ForegroundColor Cyan
& $python -m compileall `
    backend/app/services/gen4_evidence_sprint_service.py `
    scripts/run_gen4_evidence_sprint.py `
    scripts/verify_gen4_evidence_sprint_contract.py `
    tests/test_gen4_evidence_sprint_m49_m50.py
if ($LASTEXITCODE -ne 0) { throw "Compilazione fallita" }

Write-Host "[2/4] Test mirati e regressioni" -ForegroundColor Cyan
& $python -m pytest `
    tests/test_gen4_evidence_sprint_m49_m50.py `
    tests/test_gen4_history_acquisition_m48.py `
    tests/test_parser_gen4_profitability_m47.py `
    tests/test_extended_candidate_history.py -q
if ($LASTEXITCODE -ne 0) { throw "Test mirati falliti" }

Write-Host "[3/4] Verifier" -ForegroundColor Cyan
& $python scripts/verify_gen4_evidence_sprint_contract.py
if ($LASTEXITCODE -ne 0) { throw "Verifier fallito" }

Write-Host "[4/4] Alembic invariata" -ForegroundColor Cyan
$heads = (& cmd.exe /d /c "`"$python`" -m alembic heads 2>&1" | Out-String)
$current = (& cmd.exe /d /c "`"$python`" -m alembic current 2>&1" | Out-String)
if ($heads -notmatch $expectedHead -or $current -notmatch $expectedHead) {
    throw "Head Alembic inattesa"
}

Write-Host "TEST M49-M50 SUPERATI." -ForegroundColor Green
