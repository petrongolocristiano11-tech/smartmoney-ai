$ErrorActionPreference = "Stop"

$source = $PSScriptRoot
$destination = "C:\smartmoney-ai"
$backupBranch = "backup-before-extended-candidate-history-2026-07-23"

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
    "alembic\versions\f6a8d3c1e927_add_extended_candidate_history_sufficiency.py",
    "backend\app\models\candidate_history_backfill.py",
    "backend\app\models\candidate_token_compatibility.py",
    "backend\app\services\candidate_history_service.py",
    "backend\app\services\candidate_jupiter_compatibility_service.py",
    "tests\test_extended_candidate_history.py",
    "tests\test_extended_candidate_history_api.py",
    "tests\test_candidate_jupiter_compatibility_cache.py",
    "README_BACKTEST_DATA_SUFFICIENCY_EXTENDED_HISTORY.md",
    "ROLLBACK_BACKTEST_DATA_SUFFICIENCY_EXTENDED_HISTORY.md",
    "TEST_BACKTEST_DATA_SUFFICIENCY_EXTENDED_HISTORY.ps1",
    "TEST_RESULTS_BACKTEST_DATA_SUFFICIENCY_EXTENDED_HISTORY.txt",
    "PATCH_FILES_BACKTEST_DATA_SUFFICIENCY_EXTENDED_HISTORY.txt",
    "APPLY_AND_TEST_BACKTEST_DATA_SUFFICIENCY_EXTENDED_HISTORY.ps1",
    "PATCH_MANIFEST_SHA256.txt",
    "backend\app\api\discovered_wallets.py",
    "backend\app\models\__init__.py",
    "backend\app\models\candidate_backtest.py",
    "backend\app\models\discovered_wallet.py",
    "backend\app\models\live_wallet_score.py",
    "backend\app\schemas\candidate_backtest.py",
    "backend\app\schemas\discovered_wallet.py",
    "backend\app\schemas\live_platform.py",
    "backend\app\services\candidate_backtest_service.py",
    "backend\app\services\discovered_wallet_service.py",
    "backend\app\services\discovery_hydration_service.py",
    "backend\app\services\helius.py",
    "backend\app\services\live_wallet_ranking_service.py",
    "frontend\src\pages\Discovery.jsx",
    "frontend\src\services\api.js",
    "tests\test_candidate_backtest_api.py",
    "tests\test_candidate_backtest_promotion_gate.py",
    "tests\test_live_wallet_ranking_platform.py"
)

Write-Host "[1/3] Copia di $($files.Count) file completi"
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

Write-Host "[2/3] Esecuzione completa di test, migrazione e build"
powershell.exe -ExecutionPolicy Bypass -File (
    Join-Path $destination "TEST_BACKTEST_DATA_SUFFICIENCY_EXTENDED_HISTORY.ps1"
)
if ($LASTEXITCODE -ne 0) { throw "Verifica completa fallita." }

Write-Host "[3/3] Patch applicata"
Set-Location $destination
git status --short

Write-Host ""
Write-Host "PATCH APPLICATA E TESTATA CON SUCCESSO." -ForegroundColor Green
Write-Host "Backup Git: $backupBranch"
Write-Host "Non eseguire ancora commit o push finche l'output non e stato controllato."
