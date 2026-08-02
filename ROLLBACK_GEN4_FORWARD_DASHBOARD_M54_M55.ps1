param(
    [string]$BackupPath = ""
)

$ErrorActionPreference = "Stop"
$repo = "C:\smartmoney-ai"

if (-not $BackupPath) {
    $latest = Get-ChildItem `
        -Path (Join-Path $repo ".smartmoney-backups") `
        -Directory `
        -Filter "gen4-forward-dashboard-m54-m55-*" `
        -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if (-not $latest) {
        throw "Backup M54-M55 non trovato."
    }

    $BackupPath = $latest.FullName
}

$backedUpList = Join-Path $BackupPath "BACKED_UP_FILES.txt"
$newFilesList = Join-Path $BackupPath "NEW_FILES.txt"

if (-not (Test-Path -LiteralPath $backedUpList)) {
    throw "Manifest backup mancante: $backedUpList"
}

if (Test-Path -LiteralPath $newFilesList) {
    Get-Content -LiteralPath $newFilesList |
        Where-Object { $_.Trim() } |
        ForEach-Object {
            $destination = Join-Path $repo $_
            if (Test-Path -LiteralPath $destination) {
                Remove-Item -LiteralPath $destination -Recurse -Force
            }
        }
}

Get-Content -LiteralPath $backedUpList |
    Where-Object { $_.Trim() } |
    ForEach-Object {
        $source = Join-Path $BackupPath $_
        $destination = Join-Path $repo $_
        $parent = Split-Path -Parent $destination
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }

Set-Location $repo
git diff --check
Write-Host "ROLLBACK M54-M55 COMPLETATO" -ForegroundColor Green
Write-Host "Database e Alembic non sono stati modificati." -ForegroundColor Green
Write-Host "Il file .env è stato ripristinato dal backup quando presente." -ForegroundColor Green
