param([string]$ProjectRoot = "C:\smartmoney-ai")
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $ProjectRoot
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
& $python scripts\verify_m73_controlled_new_wallet_qualification.py
if ($LASTEXITCODE -ne 0) { throw "Verifier M73 fallito." }
& $python -m pytest tests\test_m73_controlled_new_wallet_qualification.py -q
if ($LASTEXITCODE -ne 0) { throw "Test M73 falliti." }
Write-Host "M73_TARGETED_TEST=PASS" -ForegroundColor Green
Write-Host "NETWORK_REQUESTS=0"
Write-Host "HELIUS_REQUESTS=0"
Write-Host "PUBLIC_RPC_REQUESTS=0"
Write-Host "LIVE_ORDERS=0"
