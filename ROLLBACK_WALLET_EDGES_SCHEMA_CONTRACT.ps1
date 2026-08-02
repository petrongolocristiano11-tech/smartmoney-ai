$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$destination = "C:\smartmoney-ai"
$python = Join-Path $destination ".venv\Scripts\python.exe"
$previousHead = "c1f3a6b9d075"
$newHead = "d2a4b7c0e186"
$latestMarker = Join-Path $destination ".smartmoney-backups\wallet-edges-schema-contract-latest.txt"
$headFixMarker = Join-Path $destination ".smartmoney-backups\wallet-edges-test-head-fix-latest.txt"

$modifiedFiles = @(
    "backend\app\models\wallet_edge.py",
    "backend\app\services\wallet_graph_engine.py"
)

$headFixFiles = @(
    "tests\test_parser_assisted_micro_live_pilot_m45.py",
    "tests\test_parser_controlled_live_submission_m38.py",
    "tests\test_parser_governed_live_position_m40.py",
    "tests\test_parser_live_incident_response_m41.py",
    "tests\test_parser_live_operational_observability_m43.py",
    "tests\test_parser_live_portfolio_risk_m42.py",
    "tests\test_parser_paper_calibration_m33.py",
    "tests\test_parser_preproduction_certification_m44.py",
    "tests\test_parser_progressive_automation_m46.py",
    "PATCH_MANIFEST_SHA256.txt"
)

$newFiles = @(
    "alembic\versions\d2a4b7c0e186_add_wallet_edges_schema_contract.py",
    "tests\test_wallet_edges_schema_contract.py",
    "scripts\verify_wallet_edges_schema_contract.py",
    "scripts\test_wallet_edges_postgresql_migration.py",
    "README_WALLET_EDGES_SCHEMA_CONTRACT.md",
    "ROLLBACK_WALLET_EDGES_SCHEMA_CONTRACT.ps1",
    "TEST_WALLET_EDGES_SCHEMA_CONTRACT.ps1",
    "TEST_RESULTS_WALLET_EDGES_SCHEMA_CONTRACT.txt",
    "PATCH_FILES_WALLET_EDGES_SCHEMA_CONTRACT.txt"
)

if (-not (Test-Path -LiteralPath $destination)) {
    throw "Repository non trovato: $destination"
}
if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment non trovato: $python"
}
if (-not (Test-Path -LiteralPath $latestMarker)) {
    throw "Marker backup patch principale non trovato: $latestMarker"
}
if (-not (Test-Path -LiteralPath $headFixMarker)) {
    throw "Marker backup correzione test non trovato: $headFixMarker"
}

$backupRoot = (Get-Content -LiteralPath $latestMarker -Raw).Trim()
$headFixBackupRoot = (Get-Content -LiteralPath $headFixMarker -Raw).Trim()
if (-not (Test-Path -LiteralPath $backupRoot)) {
    throw "Backup patch principale non trovato: $backupRoot"
}
if (-not (Test-Path -LiteralPath $headFixBackupRoot)) {
    throw "Backup correzione test non trovato: $headFixBackupRoot"
}

Set-Location $destination

Write-Host "[1/6] Verifica revisione database"
$current = (& cmd.exe /d /c "$python -m alembic current 2>&1" | Out-String)
if ($LASTEXITCODE -ne 0) {
    throw "alembic current non riuscito (exit code $LASTEXITCODE)."
}
if ($current -match $newHead) {
    Write-Host "Tentativo di downgrade protetto a $previousHead"
    Write-Host "Il downgrade verrà rifiutato automaticamente se wallet_edges contiene dati."
    & cmd.exe /d /c "$python -m alembic downgrade $previousHead 2>&1"
    if ($LASTEXITCODE -ne 0) {
        throw "Downgrade non eseguito. Se wallet_edges contiene dati, il blocco è intenzionale e nessun file è stato ripristinato."
    }
}
elseif ($current -notmatch $previousHead) {
    throw "Revisione database inattesa. Rollback interrotto."
}

Write-Host "[2/6] Ripristino file originali della patch principale"
foreach ($file in $modifiedFiles) {
    $backupFile = Join-Path $backupRoot $file
    $destinationFile = Join-Path $destination $file
    if (-not (Test-Path -LiteralPath $backupFile)) {
        throw "File backup mancante: $backupFile"
    }
    Copy-Item -LiteralPath $backupFile -Destination $destinationFile -Force
}

Write-Host "[3/6] Ripristino test storici e manifest originale"
foreach ($file in $headFixFiles) {
    $backupFile = Join-Path $headFixBackupRoot $file
    $destinationFile = Join-Path $destination $file
    if (-not (Test-Path -LiteralPath $backupFile)) {
        throw "File backup correzione test mancante: $backupFile"
    }
    Copy-Item -LiteralPath $backupFile -Destination $destinationFile -Force
}

Write-Host "[4/6] Rimozione file introdotti dalla patch"
foreach ($file in $newFiles) {
    $destinationFile = Join-Path $destination $file
    if (Test-Path -LiteralPath $destinationFile) {
        Remove-Item -LiteralPath $destinationFile -Force
    }
}

Write-Host "[5/6] Verifica head ripristinata"
$heads = (& cmd.exe /d /c "$python -m alembic heads 2>&1" | Out-String)
if ($LASTEXITCODE -ne 0) {
    throw "alembic heads non riuscito (exit code $LASTEXITCODE)."
}
if ($heads -notmatch $previousHead) {
    throw "Head sorgente non ripristinata: attesa $previousHead"
}

Write-Host "[6/6] Stato Git"
& git diff --check
if ($LASTEXITCODE -ne 0) {
    throw "git diff --check non riuscito (exit code $LASTEXITCODE)."
}
& git status --short
if ($LASTEXITCODE -ne 0) {
    throw "git status non riuscito (exit code $LASTEXITCODE)."
}

Write-Host ""
Write-Host "ROLLBACK COMPLETATO." -ForegroundColor Green
Write-Host "Database e codice sono tornati a $previousHead."
Write-Host "Nessun commit, push o deploy è stato eseguito."
