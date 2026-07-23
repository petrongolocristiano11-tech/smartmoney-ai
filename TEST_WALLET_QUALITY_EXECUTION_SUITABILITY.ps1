$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$project = "C:\smartmoney-ai"
Set-Location $project

Write-Host "[1/8] Compilazione backend"
.\.venv\Scripts\python.exe -m compileall backend

Write-Host "[2/8] Test specifici qualità e integrazione"
.\.venv\Scripts\python.exe -m pytest `
    tests/test_wallet_quality_execution_suitability.py `
    tests/test_wallet_quality_api.py `
    tests/test_active_wallet_discovery_api.py `
    tests/test_wallet_activity_ranking.py `
    tests/test_controlled_discovery_hydration.py `
    tests/test_live_wallet_ranking_platform.py `
    -q

Write-Host "[3/8] Suite backend completa"
.\.venv\Scripts\python.exe -m pytest -q

Write-Host "[4/8] Controllo Alembic"
.\.venv\Scripts\python.exe -m alembic heads
.\.venv\Scripts\python.exe -m alembic current

Write-Host "[5/8] Migrazione database locale"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current

Write-Host "[6/8] Installazione dipendenze frontend"
Set-Location "$project\frontend"
npm install

Write-Host "[7/8] Build frontend"
npm run build

Write-Host "[8/8] Controlli Git"
Set-Location $project
git diff --check
git status --short

Write-Host ""
Write-Host "WALLET QUALITY & EXECUTION SUITABILITY VERIFICATA." -ForegroundColor Green
Write-Host "Non eseguire ancora commit o push finché l'output non è stato controllato."
