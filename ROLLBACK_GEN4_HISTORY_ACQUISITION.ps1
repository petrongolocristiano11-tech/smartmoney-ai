$ErrorActionPreference = "Stop"
$project = "C:\smartmoney-ai"
Set-Location $project

if ((git rev-parse --short=7 HEAD).Trim() -ne "2bbd0e1") {
    throw "Rollback automatico previsto solo prima del commit M48, su 2bbd0e1."
}

$tracked = @(
    "backend/app/services/candidate_history_service.py",
    "tests/test_extended_candidate_history.py"
)

git restore --source=HEAD -- $tracked
if ($LASTEXITCODE -ne 0) { throw "Ripristino file tracciati fallito" }

$untracked = @(
    "backend/app/services/gen4_history_acquisition_service.py",
    "scripts/run_gen4_history_acquisition.py",
    "scripts/verify_gen4_history_acquisition_contract.py",
    "tests/test_gen4_history_acquisition_m48.py",
    "README_GEN4_HISTORY_ACQUISITION.md",
    "TEST_GEN4_HISTORY_ACQUISITION.ps1",
    "TEST_RESULTS_GEN4_HISTORY_ACQUISITION.txt",
    "ROLLBACK_GEN4_HISTORY_ACQUISITION.ps1",
    "PATCH_FILES_GEN4_HISTORY_ACQUISITION.txt"
)

foreach ($file in $untracked) {
    if (Test-Path -LiteralPath $file) {
        Remove-Item -LiteralPath $file -Force
    }
}

Write-Host "Codice M48 non committato rimosso." -ForegroundColor Green
Write-Host "Trade e metadati storici eventualmente importati preservati." -ForegroundColor Yellow
Write-Host "Head Alembic invariata: e3b5c8d1f297."
git status --short
