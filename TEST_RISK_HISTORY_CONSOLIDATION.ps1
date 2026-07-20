$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Ambiente Python non trovato: $Python"
}

Write-Host "`n[1/7] Compilazione backend e migrazione..." -ForegroundColor Cyan
& $Python -m compileall backend alembic scripts
if ($LASTEXITCODE -ne 0) { throw "compileall fallito" }

Write-Host "`n[2/7] Test backend completi..." -ForegroundColor Cyan
& $Python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "pytest fallito" }

Write-Host "`n[3/7] Applicazione migrazione Alembic..." -ForegroundColor Cyan
& $Python -m alembic heads
if ($LASTEXITCODE -ne 0) { throw "alembic heads fallito" }
& $Python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "alembic upgrade head fallito" }
& $Python -m alembic current
if ($LASTEXITCODE -ne 0) { throw "alembic current fallito" }

Write-Host "`n[4/7] Verifica OpenAPI e modelli..." -ForegroundColor Cyan
& $Python scripts\verify_autonomous_risk_operations.py
if ($LASTEXITCODE -ne 0) { throw "verifica modelli fallita" }

Write-Host "`n[5/7] Test cron Node..." -ForegroundColor Cyan
Push-Location automation
try {
    npm test
    if ($LASTEXITCODE -ne 0) { throw "test cron falliti" }
}
finally {
    Pop-Location
}

Write-Host "`n[6/7] ESLint e build frontend..." -ForegroundColor Cyan
Push-Location frontend
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci fallito" }

    npx eslint `
        src/components/liveTrading/LiveTradingOperations.jsx `
        src/components/liveTrading/LiveTradingPositions.jsx
    if ($LASTEXITCODE -ne 0) { throw "ESLint fallito" }

    npm run build
    if ($LASTEXITCODE -ne 0) { throw "build frontend fallita" }
}
finally {
    Pop-Location
}

Write-Host "`n[7/7] Controlli Git..." -ForegroundColor Cyan
git diff --check
if ($LASTEXITCODE -ne 0) { throw "git diff --check ha trovato errori" }
git status --short

Write-Host "`nTUTTI I CONTROLLI SONO TERMINATI CORRETTAMENTE." -ForegroundColor Green
Write-Host "Mantieni RUN_LIVE_POSITION_MONITOR=false fino alla verifica sul sito." -ForegroundColor Yellow
