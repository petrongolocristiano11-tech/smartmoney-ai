$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$project = "C:\smartmoney-ai"
$python = Join-Path $project ".venv\Scripts\python.exe"
$expectedHead = "d2a4b7c0e186"

function Invoke-CheckedNative {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    & $Command
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "$Description non riuscito (exit code $exitCode)."
    }
}

if (-not (Test-Path -LiteralPath $project)) {
    throw "Repository non trovato: $project"
}
if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment non trovato: $python"
}

Set-Location $project

Write-Host "[1/8] Compilazione file modificati"
Invoke-CheckedNative -Description "Compilazione" -Command {
    & $python -m compileall `
        backend/app/models/wallet_edge.py `
        backend/app/services/wallet_graph_engine.py `
        alembic/versions/d2a4b7c0e186_add_wallet_edges_schema_contract.py `
        scripts/verify_wallet_edges_schema_contract.py `
        scripts/test_wallet_edges_postgresql_migration.py `
        tests/test_wallet_edges_schema_contract.py
}

Write-Host "[2/8] Test mirati wallet_edges e regressione M31"
Invoke-CheckedNative -Description "Test mirati wallet_edges e M31" -Command {
    & $python -m pytest `
        tests/test_wallet_edges_schema_contract.py `
        tests/test_parser_unified_decision_m31.py `
        -q
}

Write-Host "[3/8] Verifier statico e OpenAPI"
Invoke-CheckedNative -Description "Verifier statico e OpenAPI" -Command {
    & $python scripts/verify_wallet_edges_schema_contract.py
}

Write-Host "[4/8] Ciclo Alembic isolato su PostgreSQL temporanei"
Invoke-CheckedNative -Description "Ciclo Alembic PostgreSQL" -Command {
    & $python scripts/test_wallet_edges_postgresql_migration.py
}

Write-Host "[5/8] Suite backend completa"
Invoke-CheckedNative -Description "Suite backend completa" -Command {
    & $python -m pytest -q
}

Write-Host "[6/8] Controllo head e current Alembic"
$heads = (& cmd.exe /d /c "$python -m alembic heads 2>&1" | Out-String)
if ($LASTEXITCODE -ne 0) {
    throw "alembic heads non riuscito (exit code $LASTEXITCODE)."
}
if ($heads -notmatch $expectedHead) {
    throw "Head Alembic inattesa. Attesa: $expectedHead"
}
Write-Host $heads.Trim()

$current = (& cmd.exe /d /c "$python -m alembic current 2>&1" | Out-String)
if ($LASTEXITCODE -ne 0) {
    throw "alembic current non riuscito (exit code $LASTEXITCODE)."
}
if ($current -notmatch $expectedHead) {
    throw "Database locale non alla revisione $expectedHead."
}
Write-Host $current.Trim()

Write-Host "[7/8] Verifica read-only dello schema database corrente"
Invoke-CheckedNative -Description "Verifica read-only database corrente" -Command {
    & $python scripts/test_wallet_edges_postgresql_migration.py --current
}

Write-Host "[8/8] Controllo Git"
Invoke-CheckedNative -Description "git diff --check" -Command {
    & git diff --check
}
& git status --short
if ($LASTEXITCODE -ne 0) {
    throw "git status non riuscito (exit code $LASTEXITCODE)."
}

Write-Host ""
Write-Host "VERIFICA WALLET_EDGES COMPLETATA SENZA ERRORI." -ForegroundColor Green
Write-Host "Head verificata: $expectedHead"
Write-Host "Nessun commit, push o deploy è stato eseguito."
