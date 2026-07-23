$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    throw "Virtual environment non trovato in $root\.venv"
}

Write-Host "[1/8] Compilazione backend"
.\.venv\Scripts\python.exe -m compileall backend
if ($LASTEXITCODE -ne 0) { throw "Compilazione backend fallita." }

Write-Host "[2/8] Test specifici Extended History e Data Sufficiency"
.\.venv\Scripts\python.exe -m pytest `
    tests/test_candidate_backtest_promotion_gate.py `
    tests/test_candidate_backtest_api.py `
    tests/test_extended_candidate_history.py `
    tests/test_extended_candidate_history_api.py `
    tests/test_candidate_jupiter_compatibility_cache.py `
    tests/test_live_wallet_ranking_platform.py `
    -q
if ($LASTEXITCODE -ne 0) { throw "Test specifici falliti." }

Write-Host "[3/8] Suite backend completa"
.\.venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Suite backend completa fallita." }

Write-Host "[4/8] Controllo Alembic"
$heads = .\.venv\Scripts\python.exe -m alembic heads
if ($LASTEXITCODE -ne 0) { throw "Controllo heads Alembic fallito." }
$heads | Write-Host
if (($heads -join "`n") -notmatch "f6a8d3c1e927") {
    throw "Head Alembic inattesa. Prevista f6a8d3c1e927."
}
.\.venv\Scripts\python.exe -m alembic current
if ($LASTEXITCODE -ne 0) { throw "Controllo current Alembic fallito." }

Write-Host "[5/8] Migrazione database locale"
.\.venv\Scripts\python.exe -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "Migrazione Alembic fallita." }
$current = .\.venv\Scripts\python.exe -m alembic current
if ($LASTEXITCODE -ne 0) { throw "Verifica migrazione Alembic fallita." }
$current | Write-Host
if (($current -join "`n") -notmatch "f6a8d3c1e927") {
    throw "Database locale non aggiornato a f6a8d3c1e927."
}

Write-Host "[6/8] Installazione e build frontend"
Set-Location "$root\frontend"
npm install
if ($LASTEXITCODE -ne 0) { throw "npm install fallito." }
npm run build
if ($LASTEXITCODE -ne 0) { throw "Build frontend fallita." }

Write-Host "[7/8] Controllo differenze Git"
Set-Location $root
git diff --check
if ($LASTEXITCODE -ne 0) { throw "git diff --check ha rilevato errori." }

Write-Host "[8/8] Stato Git"
git status --short
if ($LASTEXITCODE -ne 0) { throw "Lettura stato Git fallita." }

Write-Host ""
Write-Host "BACKTEST DATA SUFFICIENCY & EXTENDED HISTORY VERIFICATO." -ForegroundColor Green
Write-Host "Head Alembic: f6a8d3c1e927"
Write-Host "Test specifici previsti: 25. Suite locale prevista: 210 test."
Write-Host "Non eseguire ancora commit o push finche l'output non e stato controllato."
