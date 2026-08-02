$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo = "C:\smartmoney-ai"
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Virtual environment non trovato: $python" }
Set-Location $repo

& $python -m pytest `
    tests/test_gen4_forward_shadow_m52_m53.py `
    tests/test_gen4_price_integrity_m51.py `
    tests/test_parser_gen4_profitability_m47.py `
    tests/test_gen4_history_acquisition_m48.py `
    tests/test_gen4_evidence_sprint_m49_m50.py `
    -q
if ($LASTEXITCODE -ne 0) { throw "Test mirati M47-M53 falliti." }

& $python scripts/verify_gen4_forward_shadow_contract.py
if ($LASTEXITCODE -ne 0) { throw "Verifier M52-M53 fallito." }
