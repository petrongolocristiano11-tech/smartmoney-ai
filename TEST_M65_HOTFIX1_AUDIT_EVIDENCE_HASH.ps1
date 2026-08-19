param([string]$ProjectRoot = "C:\smartmoney-ai")

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$project = (Resolve-Path -LiteralPath $ProjectRoot).Path
$python = Join-Path $project ".venv\Scripts\python.exe"

& $python (Join-Path $project "scripts\verify_m65_hotfix1_audit_evidence_hash.py")
if ($LASTEXITCODE -ne 0) { throw "Verifier M65 Hotfix1 fallito." }

& $python -m pytest -q `
    (Join-Path $project "tests\test_m64_gen4_closed_trade_readonly_audit.py") `
    (Join-Path $project "tests\test_m65_gen4_definitive_wallet_gate.py") `
    (Join-Path $project "tests\test_m65_hotfix1_audit_evidence_hash.py")
if ($LASTEXITCODE -ne 0) { throw "Test M65 Hotfix1 falliti." }

Write-Host "M65_HOTFIX1_TESTS=PASS" -ForegroundColor Green
