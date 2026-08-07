param(
    [string]$ProjectRoot = "C:\smartmoney-ai"
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $ProjectRoot

$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$script = Join-Path $ProjectRoot "scripts\rollback_gen4_parallel_candidate_m61.py"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python del virtual environment non trovato: $python"
}
if (-not (Test-Path -LiteralPath $script)) {
    throw "Script rollback M61 non trovato: $script"
}

Write-Host ""
Write-Host "ROLLBACK M61 SICURO" -ForegroundColor Yellow
Write-Host "Ferma soltanto la campagna candidata, ripristina il webhook ai 2 wallet primari e conserva tutte le evidenze." -ForegroundColor Yellow
Write-Host "Non elimina righe, non esegue downgrade Alembic, non modifica la campagna primaria, non attiva Paper/LIVE." -ForegroundColor Yellow
Write-Host ""

$confirmation = Read-Host "Scrivi esattamente ROLLBACK_M61_CANDIDATE_ONLY"
if ($confirmation -cne "ROLLBACK_M61_CANDIDATE_ONLY") {
    throw "Conferma rollback M61 non valida. Nessuna modifica eseguita."
}

$oldConfirmation = $env:M61_ROLLBACK_CONFIRMATION
try {
    $env:M61_ROLLBACK_CONFIRMATION = "ROLLBACK_M61_CANDIDATE_ONLY"
    & $python $script
    if ($LASTEXITCODE -ne 0) {
        throw "Rollback operativo M61 fallito."
    }
}
finally {
    $env:M61_ROLLBACK_CONFIRMATION = $oldConfirmation
}
