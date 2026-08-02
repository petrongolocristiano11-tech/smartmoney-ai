param(
    [string]$BackupPath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo = "C:\smartmoney-ai"
Set-Location $repo

if ([string]::IsNullOrWhiteSpace($BackupPath)) {
    $BackupPath = Get-ChildItem `
        -Path (Join-Path $repo ".smartmoney-backups") `
        -Directory `
        -Filter "gen4-price-integrity-m51-*" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1 |
        ForEach-Object FullName
}

if ([string]::IsNullOrWhiteSpace($BackupPath) -or -not (Test-Path -LiteralPath $BackupPath)) {
    throw "Backup M51 non trovato."
}

$filesList = Join-Path $BackupPath "BACKED_UP_FILES.txt"
$newFilesList = Join-Path $BackupPath "NEW_FILES.txt"

if (Test-Path -LiteralPath $filesList) {
    foreach ($relative in Get-Content -LiteralPath $filesList) {
        if ([string]::IsNullOrWhiteSpace($relative)) { continue }
        $source = Join-Path $BackupPath $relative
        $destination = Join-Path $repo $relative
        $directory = Split-Path -Parent $destination
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
}

if (Test-Path -LiteralPath $newFilesList) {
    foreach ($relative in Get-Content -LiteralPath $newFilesList) {
        if ([string]::IsNullOrWhiteSpace($relative)) { continue }
        $destination = Join-Path $repo $relative
        if (Test-Path -LiteralPath $destination) {
            Remove-Item -LiteralPath $destination -Force
        }
    }
}

Write-Host "Rollback codice M51 completato." -ForegroundColor Green
Write-Host "Database invariato: nessun downgrade necessario."
git status --short
