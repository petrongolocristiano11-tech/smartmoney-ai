$ErrorActionPreference = "Stop"
$project = "C:\smartmoney-ai"
$files = @(
    "backend/app/services/gen4_evidence_sprint_service.py"
    "scripts/run_gen4_evidence_sprint.py"
    "scripts/verify_gen4_evidence_sprint_contract.py"
    "tests/test_gen4_evidence_sprint_m49_m50.py"
    "README_GEN4_EVIDENCE_SPRINT.md"
    "ROLLBACK_GEN4_EVIDENCE_SPRINT.ps1"
    "TEST_GEN4_EVIDENCE_SPRINT.ps1"
    "TEST_RESULTS_GEN4_EVIDENCE_SPRINT.txt"
    "PATCH_FILES_GEN4_EVIDENCE_SPRINT.txt"
)

Set-Location $project

Write-Host "Questo rollback rimuove soltanto il codice M49-M50." -ForegroundColor Yellow
Write-Host "I trade storici e i metadati di backfill già acquisiti vengono preservati." -ForegroundColor Yellow

foreach ($relative in $files) {
    $path = Join-Path $project $relative
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force
    }
}

Write-Host "Stato Git:" -ForegroundColor Cyan
git status --short
Write-Host "ROLLBACK CODICE M49-M50 COMPLETATO. Nessun dato storico eliminato." -ForegroundColor Green
