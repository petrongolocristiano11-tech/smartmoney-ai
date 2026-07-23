$ErrorActionPreference = "Stop"

Write-Host "=== SmartMoney AI: Active Wallet Discovery & Ranking ===" -ForegroundColor Cyan

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Ambiente virtuale non trovato in .venv. Crealo e installa requirements.txt prima del test."
}

$Python = ".\.venv\Scripts\python.exe"

Write-Host "[1/5] Compilazione backend..." -ForegroundColor Yellow
& $Python -m compileall backend

Write-Host "[2/5] Controllo head Alembic..." -ForegroundColor Yellow
& $Python -m alembic heads

Write-Host "[3/5] Test specifici Active Wallet Discovery & Ranking..." -ForegroundColor Yellow
& $Python -m pytest `
    tests/test_wallet_activity_ranking.py `
    tests/test_active_wallet_discovery_api.py `
    tests/test_discovery_resilience.py `
    tests/test_live_wallet_ranking_platform.py `
    -q

Write-Host "[4/5] Suite backend completa..." -ForegroundColor Yellow
& $Python -m pytest -q

Write-Host "[5/5] Build frontend..." -ForegroundColor Yellow
Push-Location frontend
try {
    npm ci --no-audit --no-fund
    npm run build
}
finally {
    Pop-Location
}

Write-Host "Tutte le verifiche sono terminate con successo." -ForegroundColor Green
Write-Host "Non applicare i wallet idonei e non abilitare LIVE/stream durante questa verifica." -ForegroundColor Magenta
