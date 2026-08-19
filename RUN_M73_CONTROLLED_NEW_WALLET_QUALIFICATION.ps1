param(
    [string]$ProjectRoot = "C:\smartmoney-ai",
    [string]$OutputDirectory = "",
    [string]$Confirmation = "",
    [string]$RecoveryConfirmation = "",
    [string]$SeedWallet = "",
    [string]$PublicRpcUrl = "https://api.mainnet-beta.solana.com",
    [int]$PublicRpcRequestCap = 4000,
    [int]$MaximumCandidates = 6,
    [int]$MaximumSignaturesPerCandidate = 500
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($Confirmation -ne "EXECUTE_M73_DISCOVERY_TRANCHE_MAX_9000_HELIUS_CREDITS") {
    throw "Conferma M73 richiesta: EXECUTE_M73_DISCOVERY_TRANCHE_MAX_9000_HELIUS_CREDITS"
}
if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "Repository non trovato: $ProjectRoot"
}
$project = (Resolve-Path -LiteralPath $ProjectRoot).Path
$python = Join-Path $project ".venv\Scripts\python.exe"
$runner = Join-Path $project "scripts\run_m73_controlled_new_wallet_qualification.py"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Virtualenv Python non trovato." }
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) { throw "Runner M73 non installato." }
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path ([Environment]::GetFolderPath("UserProfile")) "Downloads\smartmoney-audits"
}
$null = New-Item -ItemType Directory -Path $OutputDirectory -Force
$output = (Resolve-Path -LiteralPath $OutputDirectory).Path
if ($output.StartsWith($project, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Output M73 deve restare fuori dal repository Git."
}
function Latest([string]$Pattern, [string]$Label) {
    $item = Get-ChildItem -LiteralPath $output -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like $Pattern } |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $item) { throw "$Label non trovato in $output" }
    Write-Host "$Label acquisito: $($item.Name)"
    return $item
}
$m72 = Latest "smartmoney-m72-definitive-discovery-rotation-report-*.json" "Report M72 firmato"
$plan = Latest "smartmoney-m72-controlled-new-wallet-acquisition-plan-disarmed-*.json" "Piano M72 firmato"
$cache = Latest "smartmoney-m71-public-rpc-cache-*.json" "Cache RPC M71"
$runnerArgs = @(
    $runner,
    "--confirmation", $Confirmation,
    "--recovery-confirmation", $RecoveryConfirmation,
    "--output-dir", $output,
    "--m72-report", $m72.FullName,
    "--m72-plan", $plan.FullName,
    "--cache-input", $cache.FullName,
    "--rpc-url", $PublicRpcUrl,
    "--public-rpc-request-cap", [string]$PublicRpcRequestCap,
    "--maximum-candidates", [string]$MaximumCandidates,
    "--maximum-signatures-per-candidate", [string]$MaximumSignaturesPerCandidate
)
if (-not [string]::IsNullOrWhiteSpace($SeedWallet)) { $runnerArgs += @("--seed-wallet", $SeedWallet) }
Set-Location $project
Write-Host "M73: acquisizione controllata + qualifica Gen4" -ForegroundColor Cyan
Write-Host "Discovery expanded manual-only: tranche standard max 86/8600, hard cap 90/9000, 0 retry; poi RPC pubblico Gen4. Nessun LIVE/signer/Jupiter."
$lines = @()
if (-not [string]::IsNullOrWhiteSpace($env:DATABASE_PUBLIC_URL)) {
    Write-Host "M73_DATABASE_ENV_BOOTSTRAP=EXISTING_ENVIRONMENT"
    $lines = @(& $python @runnerArgs)
    $exitCode = $LASTEXITCODE
}
else {
    $railwayCommand = Get-Command railway.cmd -ErrorAction SilentlyContinue
    if ($null -eq $railwayCommand) {
        throw (
            "DATABASE_PUBLIC_URL non presente e railway.cmd non trovato. " +
            "M73 Hotfix2 si interrompe prima del lock e prima di Helius; nessun fallback a DATABASE_URL."
        )
    }
    $railwayArguments = @(
        "run",
        "--service", "Postgres",
        "--environment", "production",
        "--no-local",
        $python
    ) + $runnerArgs
    Write-Host "M73_DATABASE_ENV_BOOTSTRAP=RAILWAY_POSTGRES_NO_LOCAL"
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
if ($exitCode -ne 0) { throw "Runner M73 fallito con exit code $exitCode." }
$joined = $lines -join "`n"
foreach ($marker in @(
    "M73_CONTROLLED_ACQUISITION_AND_QUALIFICATION=PASS",
    "M73_HELIUS_MAXIMUM_REQUESTS=90",
    "M73_HELIUS_CREDIT_CAP=9000",
    "M73_HELIUS_RETRIES=0",
    "M73_M66_LOCAL_PARAMETER_PREFLIGHT=PASS",
    "M73_DATABASE_PUBLIC_URL_PREFLIGHT=PASS",
    "M73_M66_RUNTIME_ENV_PREFLIGHT=PASS",
    "M73_M66_RUNTIME_DATABASE_PUBLIC_URL=YES",
    "M73_M66_RUNTIME_HELIUS_API_KEY=YES_REDACTED",
    "M73_LOCK_RECOVERY_MODE=",
    "M73_HOTFIX5_POST429_LOCK_RECOVERY=",
    "OFFICIAL_REALTIME_COUNTER=83_UNCHANGED",
    "DATABASE_CANDIDATE_WRITES=0",
    "BACKEND_POSTS=0",
    "JUPITER_REQUESTS=0",
    "PAPER_ORDERS=0",
    "LIVE_ORDERS=0",
    "SIGNER_AUTHORIZED=NO",
    "SHORT_CANARY_EXECUTION_AUTHORIZED=NO",
    "MICRO_LIVE_EXECUTION_AUTHORIZED=NO",
    "M73_REPORT_FILE=",
    "M73_REPORT_SHA256=",
    "M73_EXECUTION_LOCK_FILE="
)) {
    if (-not $joined.Contains($marker)) { throw "Marker M73 mancante: $marker" }
}
Write-Host "M73_WINDOWS_WRAPPER=PASS" -ForegroundColor Green
