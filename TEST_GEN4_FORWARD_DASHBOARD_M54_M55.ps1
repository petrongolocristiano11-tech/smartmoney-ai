$ErrorActionPreference = "Stop"
Set-Location "C:\smartmoney-ai"

& ".\.venv\Scripts\python.exe" -m pytest `
    "tests/test_gen4_forward_shadow_m52_m53.py" `
    "tests/test_gen4_forward_dashboard_frontend_m54_m55.py" `
    "tests/test_api_route_integrity.py" `
    -q

if ($LASTEXITCODE -ne 0) {
    throw "Test mirati M52-M55 non superati."
}

& ".\.venv\Scripts\python.exe" `
    "scripts/verify_gen4_forward_dashboard_m54_m55.py"

if ($LASTEXITCODE -ne 0) {
    throw "Verifier dashboard M54-M55 non superato."
}

Set-Location "C:\smartmoney-ai\frontend"
npm run build

if ($LASTEXITCODE -ne 0) {
    throw "Build frontend non superato."
}
