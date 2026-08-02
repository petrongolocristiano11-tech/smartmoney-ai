param(
    [Parameter(Mandatory=$true)]
    [string]$BackupPath
)
$ErrorActionPreference = "Stop"
$repo = "C:\smartmoney-ai"
if (-not (Test-Path -LiteralPath $BackupPath)) { throw "Backup non trovato: $BackupPath" }
$backed = Join-Path $BackupPath "BACKED_UP_FILES.txt"
$new = Join-Path $BackupPath "NEW_FILES.txt"
if (Test-Path $new) {
    Get-Content $new | Where-Object { $_.Trim() } | ForEach-Object {
        $target = Join-Path $repo $_
        if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
    }
}
if (Test-Path $backed) {
    Get-Content $backed | Where-Object { $_.Trim() } | ForEach-Object {
        $source = Join-Path $BackupPath $_
        $target = Join-Path $repo $_
        $parent = Split-Path -Parent $target
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
        Copy-Item -LiteralPath $source -Destination $target -Force
    }
}
Set-Location $repo
& ".\.venv\Scripts\python.exe" -m alembic downgrade f4d6a9c2b813
if ($LASTEXITCODE -ne 0) { throw "Downgrade Alembic M56-M57 fallito." }
Write-Host "Rollback M56-M57 completato. Riavvia backend e frontend." -ForegroundColor Green
