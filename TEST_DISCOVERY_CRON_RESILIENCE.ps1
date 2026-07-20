$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Ambiente Python non trovato: $Python"
}

Write-Host "`n[1/4] Compilazione backend..." -ForegroundColor Cyan
& $Python -m compileall backend

Write-Host "`n[2/4] Test backend completi..." -ForegroundColor Cyan
& $Python -m pytest -q

Write-Host "`n[3/4] Test cron Node..." -ForegroundColor Cyan
Push-Location automation
try {
    npm test
}
finally {
    Pop-Location
}

Write-Host "`n[4/4] Build frontend..." -ForegroundColor Cyan
Push-Location frontend
try {
    npm run build
}
finally {
    Pop-Location
}

Write-Host "`nTUTTI I CONTROLLI SONO TERMINATI CORRETTAMENTE." -ForegroundColor Green
Write-Host "Ora esegui: git status --short" -ForegroundColor Green
