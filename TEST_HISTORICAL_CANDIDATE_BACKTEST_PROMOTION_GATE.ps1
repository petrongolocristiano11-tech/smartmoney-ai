$ErrorActionPreference = "Stop"
Set-Location "C:\smartmoney-ai"

Write-Host "[1/5] Compilazione backend"
.\.venv\Scripts\python.exe -m compileall backend
if ($LASTEXITCODE -ne 0) { throw "Compilazione backend fallita." }

Write-Host "[2/5] Test specifici Promotion Gate"
.\.venv\Scripts\python.exe -m pytest `
    tests/test_candidate_backtest_promotion_gate.py `
    tests/test_candidate_backtest_api.py `
    tests/test_active_wallet_discovery_api.py `
    tests/test_wallet_quality_api.py `
    tests/test_live_wallet_ranking_platform.py `
    -q
if ($LASTEXITCODE -ne 0) { throw "Test specifici falliti." }

Write-Host "[3/5] Suite backend completa"
.\.venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Suite backend completa fallita." }

Write-Host "[4/5] Controllo Alembic"
.\.venv\Scripts\python.exe -m alembic heads
if ($LASTEXITCODE -ne 0) { throw "Controllo heads Alembic fallito." }
.\.venv\Scripts\python.exe -m alembic current
if ($LASTEXITCODE -ne 0) { throw "Controllo current Alembic fallito." }

Write-Host "[5/5] Build frontend"
Set-Location "C:\smartmoney-ai\frontend"
npm install
if ($LASTEXITCODE -ne 0) { throw "npm install fallito." }
npm run build
if ($LASTEXITCODE -ne 0) { throw "Build frontend fallita." }

Set-Location "C:\smartmoney-ai"
git diff --check
if ($LASTEXITCODE -ne 0) { throw "git diff --check ha rilevato errori." }

Write-Host "TEST PROMOTION GATE COMPLETATI CON SUCCESSO." -ForegroundColor Green
