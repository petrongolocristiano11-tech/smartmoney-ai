$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    Write-Host "`n=== $Label ===" -ForegroundColor Cyan
    & $Command

    if ($LASTEXITCODE -ne 0) {
        throw "$Label fallito con codice $LASTEXITCODE."
    }
}

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Alembic = Join-Path $ProjectRoot ".venv\Scripts\alembic.exe"

if (-not (Test-Path $Python)) {
    throw "Ambiente Python non trovato: $Python"
}

if (-not (Test-Path $Alembic)) {
    throw "Alembic non trovato: $Alembic"
}

Invoke-Checked "Compilazione backend" {
    & $Python -m compileall backend
}

Invoke-Checked "Test backend completi" {
    & $Python -m pytest -q
}

Invoke-Checked "Migrazione database" {
    & $Alembic upgrade head
}

Push-Location (Join-Path $ProjectRoot "frontend")
try {
    Invoke-Checked "Installazione dipendenze frontend" {
        npm ci
    }

    Invoke-Checked "ESLint file modificati" {
        npx eslint `
            src/components/liveTrading/LiveTradingPlatform.jsx `
            src/pages/LiveTrading.jsx `
            src/services/liveTradingApi.js
    }

    Invoke-Checked "Build frontend produzione" {
        npm run build
    }
}
finally {
    Pop-Location
}

Write-Host "`n=== Verifica Git ===" -ForegroundColor Cyan
git status --short
git log -1 --oneline

Write-Host "`nTUTTI I TEST DELLE FASI 1/2/3 SONO COMPLETATI." -ForegroundColor Green
Write-Host "La modalita LIVE resta non armata finche non superi la readiness e inserisci la conferma esplicita." -ForegroundColor Yellow
