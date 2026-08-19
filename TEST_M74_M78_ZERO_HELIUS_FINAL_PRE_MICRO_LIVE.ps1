param([string]$ProjectRoot="C:\smartmoney-ai")
$ErrorActionPreference="Stop"; Set-StrictMode -Version Latest
$project=(Resolve-Path -LiteralPath $ProjectRoot).Path
$python=Join-Path $project ".venv\Scripts\python.exe"
Set-Location $project
& $python scripts\verify_m74_m78_zero_helius_final_pre_micro_live.py
if ($LASTEXITCODE -ne 0) { throw "Verifier M74-M78 fallito." }
& $python -m pytest tests\test_m74_m78_zero_helius_final_pre_micro_live.py -q
if ($LASTEXITCODE -ne 0) { throw "Test M74-M78 falliti." }
Write-Host "M74_M78_TARGETED_TESTS=PASS" -ForegroundColor Green
