$ErrorActionPreference = "Stop"

$source = $PSScriptRoot
$destination = "C:\smartmoney-ai"
$backupBranch = "backup-before-candidate-backtest-promotion-2026-07-23"

if (-not (Test-Path $destination)) {
    throw "Repository non trovato: $destination"
}

Set-Location $destination

$changes = git status --short
if ($LASTEXITCODE -ne 0) { throw "Impossibile leggere lo stato Git." }
if ($changes) {
    Write-Host $changes
    throw "Il repository contiene modifiche locali. Copia interrotta."
}

$existingBackup = git branch --list $backupBranch
if ($LASTEXITCODE -ne 0) { throw "Controllo branch di backup fallito." }
if (-not $existingBackup) {
    git branch $backupBranch
    if ($LASTEXITCODE -ne 0) { throw "Creazione branch di backup fallita." }
}

$files = @(
    "alembic\versions\e4b7c2a9d815_add_candidate_backtest_promotion_gate.py",
    "backend\app\models\candidate_backtest.py",
    "backend\app\schemas\candidate_backtest.py",
    "backend\app\services\candidate_backtest_service.py",
    "tests\test_candidate_backtest_promotion_gate.py",
    "tests\test_candidate_backtest_api.py",
    "README_HISTORICAL_CANDIDATE_BACKTEST_PROMOTION_GATE.md",
    "ROLLBACK_HISTORICAL_CANDIDATE_BACKTEST_PROMOTION_GATE.md",
    "TEST_HISTORICAL_CANDIDATE_BACKTEST_PROMOTION_GATE.ps1",
    "APPLY_AND_TEST_HISTORICAL_CANDIDATE_BACKTEST_PROMOTION_GATE.ps1",
    "TEST_RESULTS_HISTORICAL_CANDIDATE_BACKTEST_PROMOTION_GATE.txt",
    "PATCH_FILES_HISTORICAL_CANDIDATE_BACKTEST_PROMOTION_GATE.txt",
    "PATCH_MANIFEST_SHA256.txt",
    "backend\app\api\discovered_wallets.py",
    "backend\app\models\__init__.py",
    "backend\app\models\discovered_wallet.py",
    "backend\app\models\live_wallet_score.py",
    "backend\app\schemas\discovered_wallet.py",
    "backend\app\schemas\live_platform.py",
    "backend\app\services\discovered_wallet_service.py",
    "backend\app\services\live_wallet_ranking_service.py",
    "frontend\src\pages\Discovery.jsx",
    "frontend\src\services\api.js",
    "tests\test_active_wallet_discovery_api.py",
    "tests\test_wallet_quality_api.py",
    "tests\test_live_wallet_ranking_platform.py"
)

Write-Host "[1/10] Copia di $($files.Count) file completi"
foreach ($file in $files) {
    $sourceFile = Join-Path $source $file
    $destinationFile = Join-Path $destination $file
    $destinationFolder = Split-Path $destinationFile -Parent

    if (-not (Test-Path $sourceFile)) {
        throw "File sorgente mancante: $sourceFile"
    }

    New-Item -ItemType Directory -Path $destinationFolder -Force | Out-Null
    Copy-Item $sourceFile $destinationFile -Force
}

Write-Host "[2/10] Compilazione backend"
Set-Location $destination
.\.venv\Scripts\python.exe -m compileall backend
if ($LASTEXITCODE -ne 0) { throw "Compilazione backend fallita." }

Write-Host "[3/10] Test specifici Backtest e Promotion Gate"
.\.venv\Scripts\python.exe -m pytest `
    tests/test_candidate_backtest_promotion_gate.py `
    tests/test_candidate_backtest_api.py `
    tests/test_active_wallet_discovery_api.py `
    tests/test_wallet_quality_api.py `
    tests/test_live_wallet_ranking_platform.py `
    -q
if ($LASTEXITCODE -ne 0) { throw "Test specifici falliti." }

Write-Host "[4/10] Suite backend completa"
.\.venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Suite backend completa fallita." }

Write-Host "[5/10] Controllo Alembic"
.\.venv\Scripts\python.exe -m alembic heads
if ($LASTEXITCODE -ne 0) { throw "Controllo heads Alembic fallito." }
.\.venv\Scripts\python.exe -m alembic current
if ($LASTEXITCODE -ne 0) { throw "Controllo current Alembic fallito." }

Write-Host "[6/10] Migrazione database locale"
.\.venv\Scripts\python.exe -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "Migrazione Alembic fallita." }
.\.venv\Scripts\python.exe -m alembic current
if ($LASTEXITCODE -ne 0) { throw "Verifica migrazione Alembic fallita." }

Write-Host "[7/10] Installazione frontend"
Set-Location "$destination\frontend"
npm install
if ($LASTEXITCODE -ne 0) { throw "npm install fallito." }

Write-Host "[8/10] Build frontend"
npm run build
if ($LASTEXITCODE -ne 0) { throw "Build frontend fallita." }

Write-Host "[9/10] Controllo differenze"
Set-Location $destination
git diff --check
if ($LASTEXITCODE -ne 0) { throw "git diff --check ha rilevato errori." }

Write-Host "[10/10] Stato Git"
git status --short
if ($LASTEXITCODE -ne 0) { throw "Lettura stato Git fallita." }

Write-Host ""
Write-Host "PATCH APPLICATA E TESTATA CON SUCCESSO." -ForegroundColor Green
Write-Host "Head Alembic prevista: e4b7c2a9d815"
Write-Host "Test specifici previsti: 15. Suite locale prevista: circa 201 test."
Write-Host "Non eseguire commit o push finché l'output non è stato controllato."
