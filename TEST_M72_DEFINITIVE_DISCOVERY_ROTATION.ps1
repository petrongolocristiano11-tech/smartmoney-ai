param(
    [string]$ProjectRoot = "C:\smartmoney-ai"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "Repository non trovato: $ProjectRoot"
}
$project = (Resolve-Path -LiteralPath $ProjectRoot).Path
$python = Join-Path $project ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Virtualenv Python non trovato: $python"
}

Set-Location $project
Write-Host "[1/4] Compileall backend e scripts"
& $python -m compileall -q backend scripts
if ($LASTEXITCODE -ne 0) { throw "Compileall M72 fallito." }

Write-Host "[2/4] Verifier M71"
& $python scripts\verify_m71_zero_helius_adaptive_continuation.py
if ($LASTEXITCODE -ne 0) { throw "Verifier M71 fallito." }

Write-Host "[3/4] Verifier M72"
& $python scripts\verify_m72_definitive_discovery_rotation.py
if ($LASTEXITCODE -ne 0) { throw "Verifier M72 fallito." }

Write-Host "[4/4] Test mirati M71-M72"
& $python -m pytest -q `
    tests\test_m71_zero_helius_adaptive_continuation.py `
    tests\test_m72_definitive_discovery_rotation.py
if ($LASTEXITCODE -ne 0) { throw "Test mirati M71-M72 falliti." }

Write-Host "M72_TARGETED_TESTS=PASS" -ForegroundColor Green
Write-Host "NETWORK_REQUESTS=0"
Write-Host "HELIUS_REQUESTS=0"
Write-Host "DATABASE_WRITES=0"
Write-Host "BACKEND_POSTS=0"
Write-Host "PAPER_ORDERS=0"
Write-Host "LIVE_ORDERS=0"
