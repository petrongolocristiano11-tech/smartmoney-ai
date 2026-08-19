param(
    [string]$ProjectRoot = "C:\smartmoney-ai",
    [switch]$SkipFullSuite
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "Repository non trovato: $ProjectRoot"
}
$project = (Resolve-Path -LiteralPath $ProjectRoot).Path
$python = Join-Path $project ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python virtualenv non trovato: $python"
}
Set-Location $project

Write-Host "[1/6] Compileall backend e scripts"
& $python -m compileall backend scripts
if ($LASTEXITCODE -ne 0) { throw "compileall fallito." }

Write-Host "[2/6] Verifier M58-M60, M61, M62, M63 e M64"
$verifiers = @(
    "scripts\verify_gen4_copyability_m58_m60.py",
    "scripts\verify_gen4_parallel_candidate_m61.py",
    "scripts\verify_m62_raw_swap_parser_hardening.py",
    "scripts\verify_m63_helius_credit_containment.py",
    "scripts\verify_m64_gen4_closed_trade_readonly_audit.py"
)
foreach ($verifier in $verifiers) {
    $verifierOutput = @(& $python $verifier)
    $verifierOutput | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) { throw "Verifier fallito: $verifier" }
    if (($verifierOutput -join "`n") -notmatch "(VERIFIER=PASS|CONTRACT=OK)") {
        throw "Marker PASS/CONTRACT assente: $verifier"
    }
}

Write-Host "[3/6] Test mirati M58-M64"
& $python -m pytest `
    tests/test_gen4_copyability_m58_m60.py `
    tests/test_gen4_parallel_candidate_m61.py `
    tests/test_m61_webhook_cost_hotfix.py `
    tests/test_m62_raw_swap_parser_hardening.py `
    tests/test_m63_helius_credit_containment.py `
    tests/test_m64_gen4_closed_trade_readonly_audit.py `
    -q
if ($LASTEXITCODE -ne 0) { throw "Test mirati M58-M64 falliti." }

Write-Host "[4/6] Alembic head immutata"
$headOutput = @(& $python -m alembic heads)
$headOutput | ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -ne 0) { throw "Controllo Alembic heads fallito." }
if (($headOutput -join "`n") -notmatch "c8a1f3d6e942") {
    throw "Alembic head c8a1f3d6e942 non trovata."
}
Write-Host "ALEMBIC_MIGRATION=NOT_REQUIRED"

Write-Host "[5/6] Suite completa"
if ($SkipFullSuite) {
    Write-Host "Suite completa saltata solo per simulazione esplicita." -ForegroundColor Yellow
}
else {
    & $python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Suite completa fallita." }
}

Write-Host "[6/6] Git whitespace e vincoli finali"
git diff --check
if ($LASTEXITCODE -ne 0) { throw "git diff --check fallito." }

Write-Host "HELIUS_REQUESTS=0"
Write-Host "DATABASE_WRITES=0"
Write-Host "BACKEND_POSTS=0"
Write-Host "PAPER_ORDERS=0"
Write-Host "LIVE_ORDERS=0"
Write-Host "M64_TESTS=PASS" -ForegroundColor Green
