param(
    [string]$ProjectRoot = "C:\smartmoney-ai",
    [string]$OutputDirectory = "",
    [string]$PublicRpcUrl = "https://api.mainnet-beta.solana.com",
    [int]$MaximumWallets = 4,
    [int]$ExtensionSignatures = 500,
    [int]$NewCandidateSignatures = 300,
    [int]$PublicRpcRequestCap = 1800
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "Repository non trovato: $ProjectRoot"
}
$project = (Resolve-Path -LiteralPath $ProjectRoot).Path
$python = Join-Path $project ".venv\Scripts\python.exe"
$runner = Join-Path $project "scripts\run_m71_zero_helius_adaptive_continuation.py"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Virtualenv Python non trovato: $python"
}
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "Runner M71 non installato: $runner"
}
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path ([Environment]::GetFolderPath("UserProfile")) (
        "Downloads\smartmoney-audits"
    )
}
$null = New-Item -ItemType Directory -Path $OutputDirectory -Force
$output = (Resolve-Path -LiteralPath $OutputDirectory).Path
if ($output.StartsWith($project, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Gli output M71 devono restare fuori dal repository Git."
}

function Get-LatestAuditFile([string[]]$Patterns, [string]$Label) {
    foreach ($pattern in $Patterns) {
        $result = Get-ChildItem -LiteralPath $output -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like $pattern } |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -First 1
        if ($null -ne $result) {
            Write-Host "$Label acquisito: $($result.Name)"
            return $result
        }
    }
    throw "$Label non trovato in $output. Serve l'output PASS M67-M70."
}

$snapshot = Get-LatestAuditFile @(
    "smartmoney-m71-corrected-local-snapshot-*.json",
    "smartmoney-m67-unified-local-snapshot-*.json"
) "Snapshot firmato"
$rpcEvidence = Get-LatestAuditFile @(
    "smartmoney-m71-adaptive-rpc-evidence-*.json",
    "smartmoney-m67-public-rpc-evidence-*.json"
) "Evidenza RPC firmata"
$report = Get-LatestAuditFile @(
    "smartmoney-m71-updated-m67-m70-report-*.json",
    "smartmoney-m67-m70-pre-micro-live-report-*.json"
) "Report M67-M70 firmato"
$cache = Get-LatestAuditFile @(
    "smartmoney-m71-public-rpc-cache-*.json",
    "smartmoney-m67-public-rpc-cache-*.json"
) "Cache RPC SHA-256"

$arguments = @(
    $runner,
    "--confirmation", "RUN_M71_ZERO_HELIUS_ADAPTIVE_CONTINUATION_READ_ONLY",
    "--output-dir", $output,
    "--previous-snapshot", $snapshot.FullName,
    "--previous-rpc-evidence", $rpcEvidence.FullName,
    "--previous-report", $report.FullName,
    "--cache-input", $cache.FullName,
    "--rpc-url", $PublicRpcUrl,
    "--maximum-wallets", [string]$MaximumWallets,
    "--extension-signatures", [string]$ExtensionSignatures,
    "--new-candidate-signatures", [string]$NewCandidateSignatures,
    "--public-rpc-request-cap", [string]$PublicRpcRequestCap
)

Set-Location $project
Write-Host "M71: continuazione adattiva Zero-Helius" -ForegroundColor Cyan
Write-Host "Solo input JSON firmati e RPC Solana pubblico; nessun DB/Railway/Helius/Jupiter/POST/LIVE."
Write-Host "Output: $output"

$lines = @(& $python @arguments)
$exitCode = $LASTEXITCODE
$lines | ForEach-Object { Write-Host $_ }
if ($exitCode -ne 0) {
    throw "Runner M71 fallito con exit code $exitCode."
}
$joined = $lines -join "`n"
foreach ($marker in @(
    "M71_ADAPTIVE_CONTINUATION=PASS",
    "ACTIVE_CANDIDATES=",
    "ADAPTIVE_WALLETS_SELECTED=",
    "OFFICIAL_REALTIME_COUNTER=83_UNCHANGED",
    "STRICT_83_FILTER_CORRECTIONS=",
    "PRIOR_CACHE_REUSED=YES",
    "HELIUS_REQUESTS=0",
    "DATABASE_READS=0",
    "DATABASE_WRITES=0",
    "BACKEND_POSTS=0",
    "JUPITER_REQUESTS=0",
    "PAPER_ORDERS=0",
    "LIVE_ORDERS=0",
    "SIGNER_AUTHORIZED=NO",
    "MICRO_LIVE_EXECUTION_AUTHORIZED=NO",
    "M71_REPORT_FILE=",
    "M71_REPORT_SHA256="
)) {
    if (-not $joined.Contains($marker)) {
        throw "Marker M71 reale mancante: $marker"
    }
}
Write-Host "M71_WINDOWS_WRAPPER=PASS" -ForegroundColor Green
