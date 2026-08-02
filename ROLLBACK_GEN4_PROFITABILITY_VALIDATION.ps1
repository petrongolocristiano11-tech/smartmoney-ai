param(
    [string]$BackupPath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo = "C:\smartmoney-ai"
$python = Join-Path $repo ".venv\Scripts\python.exe"
$previousHead = "d2a4b7c0e186"
$currentHead = "e3b5c8d1f297"

Set-Location $repo

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python virtual environment non trovato: $python"
}

$heads = (& cmd.exe /d /c "`"$python`" -m alembic heads 2>&1" | Out-String)
if ($LASTEXITCODE -ne 0 -or $heads -notmatch $currentHead) {
    throw "Repository non alla head M47 $currentHead"
}

$current = (& cmd.exe /d /c "`"$python`" -m alembic current 2>&1" | Out-String)
if ($LASTEXITCODE -ne 0 -or $current -notmatch $currentHead) {
    throw "Database non alla head M47 $currentHead"
}

if ([string]::IsNullOrWhiteSpace($BackupPath)) {
    $BackupPath = Get-ChildItem `
        -Path (Join-Path $repo ".smartmoney-backups") `
        -Directory `
        -Filter "gen4-profitability-*" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}

if (-not $BackupPath -or -not (Test-Path -LiteralPath $BackupPath)) {
    throw "Backup M47 non trovato. Specificare -BackupPath."
}

Write-Host "[1/6] Verifica assenza run M47 persistiti" -ForegroundColor Cyan
& $python -c @'
from sqlalchemy import create_engine, text
from backend.app.core.config import settings
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
try:
    with engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM canonical_parser_gen4_profitability_runs")).scalar_one()
finally:
    engine.dispose()
if int(count) != 0:
    raise SystemExit(f"Rollback bloccato: esistono {count} run M47 persistiti")
print("Run M47 persistiti: 0")
'@
if ($LASTEXITCODE -ne 0) { throw "Rollback bloccato dai metadati M47" }

Write-Host "[2/6] Downgrade database" -ForegroundColor Cyan
& $python -m alembic downgrade $previousHead
if ($LASTEXITCODE -ne 0) { throw "Downgrade M47 fallito" }

Write-Host "[3/6] Ripristino file modificati" -ForegroundColor Cyan
$modifiedFiles = @(
    ".env.example",
    "backend/app/core/config.py",
    "backend/app/main.py",
    "backend/app/models/__init__.py",
    "backend/app/schemas/blockchain_integrity.py",
    "tests/test_wallet_edges_schema_contract.py"
)
foreach ($relative in $modifiedFiles) {
    $source = Join-Path $BackupPath $relative
    $destination = Join-Path $repo $relative
    if (-not (Test-Path -LiteralPath $source)) {
        throw "File di backup mancante: $source"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $destination -Parent) | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Force
}

Write-Host "[4/6] Rimozione file nuovi M47" -ForegroundColor Cyan
$newFiles = @(
    "backend/app/models/gen4_profitability.py",
    "backend/app/services/blockchain_parser_gen4_profitability_service.py",
    "alembic/versions/e3b5c8d1f297_add_gen4_walk_forward_profitability.py",
    "scripts/run_gen4_profitability_preview.py",
    "scripts/test_gen4_profitability_postgresql_migration.py",
    "scripts/verify_gen4_profitability_contract.py",
    "tests/test_parser_gen4_profitability_m47.py",
    "PATCH_FILES_GEN4_PROFITABILITY_VALIDATION.txt",
    "README_GEN4_PROFITABILITY_VALIDATION.md",
    "ROLLBACK_GEN4_PROFITABILITY_VALIDATION.ps1",
    "TEST_GEN4_PROFITABILITY_VALIDATION.ps1",
    "TEST_RESULTS_GEN4_PROFITABILITY_VALIDATION.txt"
)
foreach ($relative in $newFiles) {
    $path = Join-Path $repo $relative
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force
    }
}

Write-Host "[5/6] Verifica head e regressione precedente" -ForegroundColor Cyan
$headsAfter = (& cmd.exe /d /c "`"$python`" -m alembic heads 2>&1" | Out-String)
$currentAfter = (& cmd.exe /d /c "`"$python`" -m alembic current 2>&1" | Out-String)
if ($headsAfter -notmatch $previousHead -or $currentAfter -notmatch $previousHead) {
    throw "Head repository/database non ripristinata a $previousHead"
}
& $python -m pytest tests/test_wallet_edges_schema_contract.py tests/test_parser_unified_decision_m31.py -q
if ($LASTEXITCODE -ne 0) { throw "Regressione post-rollback fallita" }

Write-Host "[6/6] Stato Git" -ForegroundColor Cyan
git status --short
Write-Host "`nROLLBACK M47 COMPLETATO." -ForegroundColor Green
Write-Host "Nessun commit, push, deploy o attivazione LIVE eseguito."
