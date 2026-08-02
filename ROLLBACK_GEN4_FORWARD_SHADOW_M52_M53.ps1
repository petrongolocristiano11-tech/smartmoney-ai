param(
    [string]$BackupPath = "",
    [switch]$PurgeForwardMetadata,
    [string]$Confirmation = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo = "C:\smartmoney-ai"
$python = Join-Path $repo ".venv\Scripts\python.exe"
$targetHead = "f4d6a9c2b813"
$parentHead = "e3b5c8d1f297"
$purgeConfirmation = "PURGE_M52_M53_FORWARD_METADATA_AND_ROLLBACK"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment non trovato: $python"
}
Set-Location $repo

if ([string]::IsNullOrWhiteSpace($BackupPath)) {
    $BackupPath = Get-ChildItem `
        -Path (Join-Path $repo ".smartmoney-backups") `
        -Directory `
        -Filter "gen4-forward-shadow-m52-m53-*" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1 |
        ForEach-Object FullName
}
if ([string]::IsNullOrWhiteSpace($BackupPath) -or -not (Test-Path -LiteralPath $BackupPath)) {
    throw "Backup M52-M53 non trovato."
}

function Get-AlembicCurrent {
    $output = (& cmd.exe /d /c "`"$python`" -m alembic current 2>&1" | Out-String)
    if ($LASTEXITCODE -ne 0) { throw "Impossibile leggere Alembic current: $output" }
    return $output
}

$current = Get-AlembicCurrent
if ($current -match $targetHead) {
    $countScript = Join-Path $env:TEMP "smartmoney_m52_m53_metadata_count.py"
    @'
from pathlib import Path
import os
import sys

PROJECT_ROOT = Path(r"C:\smartmoney-ai")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from sqlalchemy import text
from backend.app.database.session import SessionLocal

TABLES = (
    "canonical_parser_gen4_forward_decisions",
    "canonical_parser_gen4_forward_cycles",
    "canonical_parser_gen4_forward_campaigns",
)
with SessionLocal() as db:
    total = 0
    for table in TABLES:
        count = int(db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())
        print(f"{table}={count}")
        total += count
    print(f"TOTAL={total}")
'@ | Set-Content -LiteralPath $countScript -Encoding UTF8

    $countOutput = (& $python $countScript 2>&1 | Out-String)
    $countExit = $LASTEXITCODE
    Remove-Item -LiteralPath $countScript -Force -ErrorAction SilentlyContinue
    if ($countExit -ne 0) { throw "Conteggio metadata forward non riuscito: $countOutput" }
    Write-Host $countOutput.TrimEnd()

    $totalMatch = [regex]::Match($countOutput, "TOTAL=(\d+)")
    if (-not $totalMatch.Success) { throw "Conteggio metadata forward non interpretabile." }
    $total = [int]$totalMatch.Groups[1].Value

    if ($total -gt 0) {
        if (-not $PurgeForwardMetadata -or $Confirmation -ne $purgeConfirmation) {
            throw (
                "Rollback rifiutato: esistono $total record forward. " +
                "Per eliminarli intenzionalmente usare -PurgeForwardMetadata " +
                "-Confirmation '$purgeConfirmation'."
            )
        }
        $purgeScript = Join-Path $env:TEMP "smartmoney_m52_m53_metadata_purge.py"
        @'
from pathlib import Path
import os
import sys

PROJECT_ROOT = Path(r"C:\smartmoney-ai")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from sqlalchemy import text
from backend.app.database.session import SessionLocal

with SessionLocal() as db:
    db.execute(text("DELETE FROM canonical_parser_gen4_forward_decisions"))
    db.execute(text("DELETE FROM canonical_parser_gen4_forward_cycles"))
    db.execute(text("DELETE FROM canonical_parser_gen4_forward_campaigns"))
    db.commit()
print("Metadata M52-M53 eliminati esplicitamente.")
'@ | Set-Content -LiteralPath $purgeScript -Encoding UTF8
        & $python $purgeScript
        $purgeExit = $LASTEXITCODE
        Remove-Item -LiteralPath $purgeScript -Force -ErrorAction SilentlyContinue
        if ($purgeExit -ne 0) { throw "Eliminazione metadata forward non riuscita." }
    }

    & $python -m alembic downgrade $parentHead
    if ($LASTEXITCODE -ne 0) { throw "Downgrade Alembic M52-M53 non riuscito." }
    $current = Get-AlembicCurrent
    if ($current -notmatch $parentHead) {
        throw "Downgrade incompleto. Alembic current: $current"
    }
} elseif ($current -notmatch $parentHead) {
    throw "Head Alembic inattesa. Attese: $targetHead oppure $parentHead. Output: $current"
}

$backedUpList = Join-Path $BackupPath "BACKED_UP_FILES.txt"
$newFilesList = Join-Path $BackupPath "NEW_FILES.txt"

if (Test-Path -LiteralPath $backedUpList) {
    foreach ($relative in Get-Content -LiteralPath $backedUpList) {
        if ([string]::IsNullOrWhiteSpace($relative)) { continue }
        $source = Join-Path $BackupPath $relative
        if (-not (Test-Path -LiteralPath $source)) {
            throw "File di backup mancante: $relative"
        }
        $destination = Join-Path $repo $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
}

if (Test-Path -LiteralPath $newFilesList) {
    foreach ($relative in Get-Content -LiteralPath $newFilesList) {
        if ([string]::IsNullOrWhiteSpace($relative)) { continue }
        $destination = Join-Path $repo $relative
        if (Test-Path -LiteralPath $destination) {
            Remove-Item -LiteralPath $destination -Force
        }
    }
}

Write-Host "Rollback M52-M53 completato." -ForegroundColor Green
Write-Host "Alembic/database: $parentHead"
Write-Host "Backup ripristinato: $BackupPath"
Write-Host "Nessun dato non-M52-M53, ordine paper/live o transazione modificato."
git status --short
