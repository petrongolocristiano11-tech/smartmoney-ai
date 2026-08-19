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
& $python -m compileall -q backend scripts tests
if ($LASTEXITCODE -ne 0) { throw "Compileall M71 fallito." }

& $python scripts\verify_m67_m70_zero_helius_pre_micro_live.py
if ($LASTEXITCODE -ne 0) { throw "Verifier M67-M70 aggiornato fallito." }

& $python scripts\verify_m71_zero_helius_adaptive_continuation.py
if ($LASTEXITCODE -ne 0) { throw "Verifier M71 fallito." }

& $python -m pytest tests\test_m67_m70_zero_helius_pre_micro_live.py `
    tests\test_m71_zero_helius_adaptive_continuation.py -q
if ($LASTEXITCODE -ne 0) { throw "Test mirati M67-M71 falliti." }

Write-Host "M71_TARGETED_TESTS=PASS" -ForegroundColor Green
Write-Host "NETWORK_REQUESTS=0"
Write-Host "HELIUS_REQUESTS=0"
Write-Host "DATABASE_READS=0"
Write-Host "DATABASE_WRITES=0"
Write-Host "BACKEND_POSTS=0"
Write-Host "JUPITER_REQUESTS=0"
Write-Host "PAPER_ORDERS=0"
Write-Host "LIVE_ORDERS=0"
