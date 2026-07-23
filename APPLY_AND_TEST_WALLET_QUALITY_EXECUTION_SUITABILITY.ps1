$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$source = $PSScriptRoot
$destination = "C:\smartmoney-ai"
$backupBranch = "backup-before-wallet-quality-2026-07-23"

if (-not (Test-Path $destination)) {
    throw "Repository non trovato: $destination"
}

Set-Location $destination

$changes = git status --short
if ($changes) {
    Write-Host $changes
    throw "Il repository contiene modifiche locali. Copia interrotta."
}

if (-not (git branch --list $backupBranch)) {
    git branch $backupBranch
}

$files = @(
    "alembic\versions\c9e4a7f2d631_add_wallet_quality_execution_suitability.py",
    "backend\app\services\wallet_quality_service.py",
    "tests\test_wallet_quality_execution_suitability.py",
    "tests\test_wallet_quality_api.py",
    "README_WALLET_QUALITY_EXECUTION_SUITABILITY.md",
    "ROLLBACK_WALLET_QUALITY_EXECUTION_SUITABILITY.md",
    "TEST_WALLET_QUALITY_EXECUTION_SUITABILITY.ps1",
    "APPLY_AND_TEST_WALLET_QUALITY_EXECUTION_SUITABILITY.ps1",
    "TEST_RESULTS_WALLET_QUALITY_EXECUTION_SUITABILITY.txt",
    "PATCH_FILES_WALLET_QUALITY_EXECUTION_SUITABILITY.txt",
    "PATCH_MANIFEST_SHA256.txt",
    "backend\app\api\discovered_wallets.py",
    "backend\app\models\discovered_wallet.py",
    "backend\app\models\live_wallet_score.py",
    "backend\app\schemas\discovered_wallet.py",
    "backend\app\schemas\live_platform.py",
    "backend\app\services\discovered_wallet_service.py",
    "backend\app\services\discovery_engine.py",
    "backend\app\services\discovery_hydration_service.py",
    "backend\app\services\live_wallet_ranking_service.py",
    "backend\app\services\smart_discovery_engine.py",
    "backend\app\services\wallet_activity_service.py",
    "frontend\src\components\liveTrading\LiveTradingPlatform.jsx",
    "frontend\src\pages\Discovery.jsx",
    "frontend\src\services\api.js",
    "tests\test_active_wallet_discovery_api.py",
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

Write-Host "[3/10] Test specifici qualità e integrazione"
.\.venv\Scripts\python.exe -m pytest `
    tests/test_wallet_quality_execution_suitability.py `
    tests/test_wallet_quality_api.py `
    tests/test_active_wallet_discovery_api.py `
    tests/test_wallet_activity_ranking.py `
    tests/test_controlled_discovery_hydration.py `
    tests/test_live_wallet_ranking_platform.py `
    -q

Write-Host "[4/10] Suite backend completa"
.\.venv\Scripts\python.exe -m pytest -q

Write-Host "[5/10] Controllo Alembic"
.\.venv\Scripts\python.exe -m alembic heads
.\.venv\Scripts\python.exe -m alembic current

Write-Host "[6/10] Migrazione database locale"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current

Write-Host "[7/10] Installazione frontend"
Set-Location "$destination\frontend"
npm install

Write-Host "[8/10] Build frontend"
npm run build

Write-Host "[9/10] Controllo differenze"
Set-Location $destination
git diff --check

Write-Host "[10/10] Stato Git"
git status --short

Write-Host ""
Write-Host "PATCH APPLICATA E TESTATA CON SUCCESSO." -ForegroundColor Green
Write-Host "Head Alembic prevista: c9e4a7f2d631"
Write-Host "Non eseguire ancora commit o push finché l'output non è stato controllato."
