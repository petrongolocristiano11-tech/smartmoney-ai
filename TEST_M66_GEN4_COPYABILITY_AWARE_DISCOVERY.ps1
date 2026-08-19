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

& $python -m compileall backend scripts tests
if ($LASTEXITCODE -ne 0) { throw "Compileall M66 fallito." }

& $python scripts\verify_m66_gen4_copyability_aware_discovery.py
if ($LASTEXITCODE -ne 0) { throw "Verifier M66 fallito." }

& $python -m pytest `
    tests/test_m66_gen4_copyability_aware_discovery.py `
    tests/test_m66_gen4_copyability_aware_discovery_api.py `
    tests/test_m66_controlled_helius_discovery.py `
    tests/test_wallet_activity_ranking.py `
    tests/test_wallet_quality_api.py `
    tests/test_wallet_quality_execution_suitability.py `
    -q
if ($LASTEXITCODE -ne 0) { throw "Test mirati M66 falliti." }

Write-Host "M66_TARGETED_TESTS=PASS" -ForegroundColor Green
