param(
    [string]$ProjectRoot = "C:\smartmoney-ai",
    [string]$OutputDirectory = "",
    [string]$Snapshot = "",
    [int]$Limit = 500,
    [int]$MaximumSelectedWallets = 3
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "Repository non trovato: $ProjectRoot"
}
$project = (Resolve-Path -LiteralPath $ProjectRoot).Path
$python = Join-Path $project ".venv\Scripts\python.exe"
$runner = Join-Path $project "scripts\run_m66_gen4_copyability_aware_discovery.py"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Virtualenv Python non trovato: $python"
}
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "Runner M66 non installato: $runner"
}
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path ([Environment]::GetFolderPath("UserProfile")) (
        "Downloads\smartmoney-audits"
    )
}
$null = New-Item -ItemType Directory -Path $OutputDirectory -Force
$output = (Resolve-Path -LiteralPath $OutputDirectory).Path
if ($output.StartsWith($project, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Gli output M66 devono restare fuori dal repository Git."
}

$arguments = @(
    $runner,
    "--confirmation", "RUN_M66_GEN4_COPYABILITY_AWARE_DISCOVERY_READ_ONLY",
    "--output-dir", $output,
    "--limit", [string]$Limit,
    "--maximum-selected-wallets", [string]$MaximumSelectedWallets
)
if (-not [string]::IsNullOrWhiteSpace($Snapshot)) {
    $arguments += @("--snapshot", $Snapshot)
}

Set-Location $project
Write-Host "M66: Discovery definitiva cached-only e read-only" -ForegroundColor Cyan
Write-Host "Il comando non usa Helius, Jupiter, backend POST o scritture DB."

$lines = @()
if (-not [string]::IsNullOrWhiteSpace($Snapshot)) {
    $lines = @(& $python @arguments)
    $exitCode = $LASTEXITCODE
}
elseif (-not [string]::IsNullOrWhiteSpace($env:DATABASE_PUBLIC_URL)) {
    $lines = @(& $python @arguments)
    $exitCode = $LASTEXITCODE
}
else {
    $railwayCommand = Get-Command railway.cmd -ErrorAction SilentlyContinue
    if ($null -eq $railwayCommand) {
        throw (
            "DATABASE_PUBLIC_URL non presente e railway.cmd non trovato. " +
            "M66 e stato interrotto senza fallback a DATABASE_URL."
        )
    }
    $railwayArguments = @(
        "run",
        "--service", "Postgres",
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
    throw "Runner M66 fallito con exit code $exitCode."
}
$joined = $lines -join "`n"
foreach ($marker in @(
    "M66_DISCOVERY_EVALUATION=PASS",
    "CACHED_WALLETS_TOTAL_ZERO_HELIUS_CREDITS=",
    "CACHED_WALLETS_SCANNED_ZERO_HELIUS_CREDITS=",
    "CACHED_TRADE_ROWS_LIFETIME_ZERO_HELIUS_CREDITS=",
    "CACHED_TRADE_ROWS_7D_ZERO_HELIUS_CREDITS=",
    "CACHED_WALLETS_WITH_LOCAL_TRADE_EVIDENCE=",
    "CACHED_WALLETS_WITH_RECENT_LOCAL_TRADE_EVIDENCE=",
    "CACHED_WALLETS_PASSING_ZERO_CREDIT_TRADE_PRESCREEN=",
    "CACHED_WALLETS_WITHOUT_LOCAL_TRADE_EVIDENCE=",
    "PUBLIC_RPC_REQUESTS_EXECUTED=0",
    "AUTOMATIC_ACQUISITION=NO",
    "DISCOVERY_CRON_REACTIVATED=NO",
    "HELIUS_REQUESTS=0",
    "DATABASE_WRITES=0",
    "BACKEND_POSTS=0",
    "JUPITER_REQUESTS=0",
    "PAPER_ORDERS=0",
    "LIVE_ORDERS=0",
    "MICRO_LIVE_EXECUTION_AUTHORIZED=NO",
    "AUTOMATIC_LIVE_ACTIVATION=NO",
    "SIGNER_AUTHORIZED=NO",
    "HISTORICAL_JUPITER_QUOTES_INVENTED=NO"
)) {
    if (-not $joined.Contains($marker)) {
        throw "Marker M66 reale mancante: $marker"
    }
}
Write-Host "M66_DISCOVERY_WRAPPER=PASS" -ForegroundColor Green
