param(
    [string]$ProjectRoot = "C:\smartmoney-ai",
    [string]$OutputDirectory = "",
    [string]$PublicRpcUrl = "https://api.mainnet-beta.solana.com",
    [int]$WalletLimit = 500,
    [int]$MaximumDeepWallets = 3,
    [int]$MaximumSignaturesPerWallet = 150,
    [int]$PublicRpcRequestCap = 600
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "Repository non trovato: $ProjectRoot"
}
$project = (Resolve-Path -LiteralPath $ProjectRoot).Path
$python = Join-Path $project ".venv\Scripts\python.exe"
$runner = Join-Path $project "scripts\run_m67_m70_zero_helius_pre_micro_live.py"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Virtualenv Python non trovato: $python"
}
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "Runner M67-M70 non installato: $runner"
}
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path ([Environment]::GetFolderPath("UserProfile")) (
        "Downloads\smartmoney-audits"
    )
}
$null = New-Item -ItemType Directory -Path $OutputDirectory -Force
$output = (Resolve-Path -LiteralPath $OutputDirectory).Path
if ($output.StartsWith($project, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Gli output M67-M70 devono restare fuori dal repository Git."
}

function Get-LatestAuditFile([string]$Pattern) {
    $result = Get-ChildItem -LiteralPath $output -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like $Pattern } |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    return $result
}

$arguments = @(
    $runner,
    "--confirmation", "RUN_M67_M70_ZERO_HELIUS_READ_ONLY",
    "--output-dir", $output,
    "--rpc-url", $PublicRpcUrl,
    "--wallet-limit", [string]$WalletLimit,
    "--maximum-deep-wallets", [string]$MaximumDeepWallets,
    "--maximum-signatures-per-wallet", [string]$MaximumSignaturesPerWallet,
    "--public-rpc-request-cap", [string]$PublicRpcRequestCap
)

$latestCache = Get-LatestAuditFile "smartmoney-m67-public-rpc-cache-*.json"
if ($null -ne $latestCache) {
    $arguments += @("--cache-input", $latestCache.FullName)
    Write-Host "Cache RPC SHA-256 riutilizzata: $($latestCache.Name)"
}
$latestM64 = Get-LatestAuditFile "smartmoney-m64-83-plus-17-readonly-audit-*.json"
if ($null -ne $latestM64) {
    $arguments += @("--m64-report", $latestM64.FullName)
    Write-Host "Report M64 acquisito: $($latestM64.Name)"
}
$latestM65 = Get-LatestAuditFile "smartmoney-m65-definitive-wallet-gate-*.json"
if ($null -ne $latestM65) {
    $arguments += @("--m65-report", $latestM65.FullName)
    Write-Host "Report M65 acquisito: $($latestM65.Name)"
}

Set-Location $project
Write-Host "M67-M70: fondazione Zero-Helius pre-Micro-Live" -ForegroundColor Cyan
Write-Host "Database read-only; RPC Solana pubblico con cap hard; nessun Helius/Jupiter/POST/LIVE."
Write-Host "Output: $output"

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
            "M67-M70 e stato interrotto senza fallback a DATABASE_URL."
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
    throw "Runner M67-M70 fallito con exit code $exitCode."
}
$joined = $lines -join "`n"
foreach ($marker in @(
    "M67_M70_EVALUATION=PASS",
    "WALLETS_EVALUATED=",
    "ACTIVE_PUBLIC_RPC_CANDIDATES=",
    "DEEP_WALLETS_ANALYZED=",
    "QUALIFIED_PENDING_SHORT_CANARY=",
    "SELECTED_WALLETS=",
    "PUBLIC_RPC_REQUEST_CAP=",
    "PUBLIC_RPC_REQUESTS=",
    "HELIUS_REQUESTS=0",
    "DATABASE_WRITES=0",
    "BACKEND_POSTS=0",
    "JUPITER_REQUESTS=0",
    "PAPER_ORDERS=0",
    "LIVE_ORDERS=0",
    "SIGNER_AUTHORIZED=NO",
    "MICRO_LIVE_EXECUTION_AUTHORIZED=NO",
    "AUTOMATIC_LIVE_ACTIVATION=NO",
    "RECOVERY_COUNTS_AS_REALTIME_PROOF=NO",
    "HISTORICAL_JUPITER_QUOTES_INVENTED=NO",
    "PRE_MICRO_LIVE_FOUNDATION=PREPARED_DISARMED",
    "PRE_MICRO_LIVE_REPORT_FILE=",
    "PRE_MICRO_LIVE_REPORT_SHA256="
)) {
    if (-not $joined.Contains($marker)) {
        throw "Marker M67-M70 reale mancante: $marker"
    }
}
Write-Host "M67_M70_WINDOWS_WRAPPER=PASS" -ForegroundColor Green
