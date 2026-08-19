param(
    [string]$ProjectRoot = "C:\smartmoney-ai",
    [string]$OutputDirectory = "",
    [string]$SeedWallet = "Bs34SxJUSjUntbsWDEZrFKEcCdJfSuF9KiwtFdJ1Tfsd",
    [string]$Confirmation = "",
    [string]$CacheInput = "",
    [int]$MaximumSeedTokens = 15,
    [int]$MaximumCandidateWallets = 70
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$requiredConfirmation = "SPEND_MAX_9000_HELIUS_CREDITS_FOR_M66_DISCOVERY_TRANCHE"
if ($Confirmation -cne $requiredConfirmation) {
    throw (
        "Conferma esplicita richiesta. Usa -Confirmation `"" +
        $requiredConfirmation + "`". Nessun credito e stato speso."
    )
}
if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "Repository non trovato: $ProjectRoot"
}
$project = (Resolve-Path -LiteralPath $ProjectRoot).Path
$python = Join-Path $project ".venv\Scripts\python.exe"
$runner = Join-Path $project "scripts\run_m66_controlled_helius_discovery.py"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Virtualenv Python non trovato: $python"
}
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "Runner Helius M66 non installato: $runner"
}
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path ([Environment]::GetFolderPath("UserProfile")) (
        "Downloads\smartmoney-audits"
    )
}
$null = New-Item -ItemType Directory -Path $OutputDirectory -Force
$output = (Resolve-Path -LiteralPath $OutputDirectory).Path
if ($output.StartsWith($project, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Gli output Helius M66 devono restare fuori dal repository Git."
}

if ([string]::IsNullOrWhiteSpace($CacheInput)) {
    $latestCache = Get-ChildItem -LiteralPath $output -File -Filter (
        "smartmoney-m66-helius-request-cache-*.json"
    ) | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
    if ($null -ne $latestCache) {
        $CacheInput = $latestCache.FullName
    }
}

$arguments = @(
    $runner,
    "--confirmation", $requiredConfirmation,
    "--output-dir", $output,
    "--seed-wallet", $SeedWallet,
    "--maximum-seed-tokens", [string]$MaximumSeedTokens,
    "--maximum-candidate-wallets", [string]$MaximumCandidateWallets
)
if (-not [string]::IsNullOrWhiteSpace($CacheInput)) {
    $arguments += @("--cache-input", $CacheInput)
}

Set-Location $project
Write-Host "M66: Discovery Helius controllata di nuovi wallet" -ForegroundColor Cyan
Write-Host "Tranche standard: max 86 chiamate / 8600 crediti; hard cap codice: 90 / 9000; retry: 0."
Write-Host "Cache esistente: $(-not [string]::IsNullOrWhiteSpace($CacheInput))"
Write-Host "Cron, campagne, feed, signer e LIVE restano invariati."

$lines = @()
if (-not [string]::IsNullOrWhiteSpace($env:DATABASE_PUBLIC_URL)) {
    $lines = @(& $python @arguments)
    $exitCode = $LASTEXITCODE
}
else {
    $railwayCommand = Get-Command railway.cmd -ErrorAction SilentlyContinue
    if ($null -eq $railwayCommand) {
        throw (
            "DATABASE_PUBLIC_URL non presente e railway.cmd non trovato. " +
            "Nessuna richiesta Helius eseguita."
        )
    }
    $railwayArguments = @(
        "run",
        "--service", "smartmoney-ai",
        "--environment", "production",
        "--no-local",
        $python
    ) + $arguments
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $lines = @(& $railwayCommand.Source @railwayArguments)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

$lines | ForEach-Object { Write-Host $_ }
if ($exitCode -ne 0) {
    throw "Runner Helius M66 fallito con exit code $exitCode."
}
$joined = $lines -join "`n"
foreach ($marker in @(
    "M66_CONTROLLED_HELIUS_DISCOVERY=PASS",
    "HELIUS_REQUEST_CAP=86",
    "HELIUS_CREDIT_CAP=8600",
    "HELIUS_RETRIES=0",
    "AUTOMATIC_ENHANCED_POLLING=NO",
    "CANDIDATE_DATABASE_WRITES=0",
    "RAW_CAPTURE_WRITES=0",
    "DATABASE_WRITE_SCOPE=HELIUS_CREDIT_GUARD_RESERVATIONS_ONLY",
    "BACKEND_POSTS=0",
    "DISCOVERY_CRON_REACTIVATED=NO",
    "PRIMARY_CAMPAIGN_REACTIVATED=NO",
    "OLD_FORWARD_FEED_REACTIVATED=NO",
    "OFFICIAL_REALTIME_COUNTER_MUTATED=NO",
    "SHORT_CANARY_ACTIVATED=NO",
    "MICRO_LIVE_EXECUTION_AUTHORIZED=NO",
    "SIGNER_AUTHORIZED=NO"
)) {
    if (-not $joined.Contains($marker)) {
        throw "Marker Helius M66 reale mancante: $marker"
    }
}
Write-Host "M66_CONTROLLED_HELIUS_WRAPPER=PASS" -ForegroundColor Green
