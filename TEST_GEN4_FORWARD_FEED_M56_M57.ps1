$ErrorActionPreference = "Stop"
Set-Location "C:\smartmoney-ai"
& ".\.venv\Scripts\python.exe" -m pytest `
    tests/test_gen4_forward_feed_m56_m57.py `
    tests/test_gen4_forward_feed_frontend_m56_m57.py `
    tests/test_gen4_forward_shadow_m52_m53.py `
    tests/test_gen4_forward_dashboard_frontend_m54_m55.py -q
if ($LASTEXITCODE -ne 0) { throw "Test M52-M57 falliti." }
& ".\.venv\Scripts\python.exe" scripts/verify_gen4_forward_feed_m56_m57.py
if ($LASTEXITCODE -ne 0) { throw "Verifier M56-M57 fallito." }
Set-Location "C:\smartmoney-ai\frontend"
npm run build
if ($LASTEXITCODE -ne 0) { throw "Build frontend fallito." }
