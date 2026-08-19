param(
    [string]$ProjectRoot = "C:\smartmoney-ai",
    [string]$OutputDirectory = "",
    [string]$PublicRpcUrl = "https://api.mainnet-beta.solana.com",
    [int]$MaximumSignatures = 5000
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "Repository non trovato: $ProjectRoot"
}
$project = (Resolve-Path -LiteralPath $ProjectRoot).Path
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path ([Environment]::GetFolderPath("UserProfile")) (
        "Downloads\smartmoney-audits"
    )
}
$null = New-Item -ItemType Directory -Path $OutputDirectory -Force
$output = (Resolve-Path -LiteralPath $OutputDirectory).Path
if ($output.StartsWith($project, [StringComparison]::OrdinalIgnoreCase)) {
    throw "La cartella audit deve restare fuori dal repository Git."
}

$startedAt = [DateTime]::UtcNow
$auditWrapper = Join-Path $project "RUN_M64_GEN4_CLOSED_TRADE_READONLY_AUDIT.ps1"
$gateWrapper = Join-Path $project "RUN_M65_GEN4_DEFINITIVE_WALLET_GATE.ps1"
if (-not (Test-Path -LiteralPath $auditWrapper -PathType Leaf)) {
    throw "Wrapper M64 non installato."
}
if (-not (Test-Path -LiteralPath $gateWrapper -PathType Leaf)) {
    throw "Wrapper M65 non installato."
}

Write-Host "[1/2] Audit pubblico M64 read-only" -ForegroundColor Cyan
& powershell.exe -ExecutionPolicy Bypass -File $auditWrapper `
    -ProjectRoot $project `
    -OutputDirectory $output `
    -PublicRpcUrl $PublicRpcUrl `
    -MaximumSignatures $MaximumSignatures
if ($LASTEXITCODE -ne 0) { throw "Audit M64 fallito." }

$auditReport = Get-ChildItem -LiteralPath $output -File |
    Where-Object {
        $_.Name -like "smartmoney-m64-83-plus-17-readonly-audit-*.json" -and
        $_.LastWriteTimeUtc -ge $startedAt.AddMinutes(-1)
    } |
    Sort-Object LastWriteTimeUtc -Descending |
    Select-Object -First 1
$rawEvidence = Get-ChildItem -LiteralPath $output -File |
    Where-Object {
        $_.Name -like "smartmoney-m64-public-raw-evidence-*.json" -and
        $_.LastWriteTimeUtc -ge $startedAt.AddMinutes(-1)
    } |
    Sort-Object LastWriteTimeUtc -Descending |
    Select-Object -First 1
if ($null -eq $auditReport -or $null -eq $rawEvidence) {
    throw "La coppia di output M64 appena generata non e stata trovata."
}

Write-Host "[2/2] Gate definitivo M65" -ForegroundColor Cyan
& powershell.exe -ExecutionPolicy Bypass -File $gateWrapper `
    -ProjectRoot $project `
    -AuditReport $auditReport.FullName `
    -RawEvidence $rawEvidence.FullName `
    -OutputDirectory $output
if ($LASTEXITCODE -ne 0) { throw "Gate M65 fallito." }

Write-Host "M65_FULL_READONLY_AUDIT_AND_GATE=PASS" -ForegroundColor Green
Write-Host "OFFICIAL_COUNTER_MUTATED=NO"
Write-Host "RECOVERY_COUNTS_AS_REALTIME_PROOF=NO"
Write-Host "HELIUS_REQUESTS=0"
Write-Host "DATABASE_WRITES=0"
Write-Host "BACKEND_POSTS=0"
Write-Host "MICRO_LIVE_EXECUTION_AUTHORIZED=NO"
