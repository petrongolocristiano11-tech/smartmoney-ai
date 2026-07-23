$ErrorActionPreference = "Stop"

Set-Location C:\smartmoney-ai

Write-Host "[1/7] Compilazione backend"
.\.venv\Scripts\python.exe -m compileall backend

Write-Host "[2/7] Test specifici Hydration"
.\.venv\Scripts\python.exe -m pytest `
  tests/test_controlled_discovery_hydration.py `
  tests/test_trade_historical_timestamp.py `
  tests/test_active_wallet_discovery_api.py `
  tests/test_wallet_activity_ranking.py `
  -q

Write-Host "[3/7] Suite completa"
.\.venv\Scripts\python.exe -m pytest -q

Write-Host "[4/7] Head e revisione Alembic corrente"
.\.venv\Scripts\python.exe -m alembic heads
.\.venv\Scripts\python.exe -m alembic current

Write-Host "[5/7] Migrazione locale"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current

Write-Host "[6/7] Build frontend"
Set-Location C:\smartmoney-ai\frontend
npm install
npm run build

Write-Host "[7/7] Controllo Git"
Set-Location C:\smartmoney-ai
git diff --check
git status --short

Write-Host "Verifica Controlled Discovery Hydration completata."
