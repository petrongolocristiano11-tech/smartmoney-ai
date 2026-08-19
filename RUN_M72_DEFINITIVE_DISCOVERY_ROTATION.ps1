param(
    [string]$ProjectRoot = "C:\smartmoney-ai",
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "Repository non trovato: $ProjectRoot"
}
$project = (Resolve-Path -LiteralPath $ProjectRoot).Path
$python = Join-Path $project ".venv\Scripts\python.exe"
$runner = Join-Path $project "scripts\run_m72_definitive_discovery_rotation.py"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Virtualenv Python non trovato: $python"
}
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "Runner M72 non installato: $runner"
}
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path ([Environment]::GetFolderPath("UserProfile")) (
        "Downloads\smartmoney-audits"
    )
}
$null = New-Item -ItemType Directory -Path $OutputDirectory -Force
$output = (Resolve-Path -LiteralPath $OutputDirectory).Path
if ($output.StartsWith($project, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Gli output M72 devono restare fuori dal repository Git."
}

function Get-LatestAuditFile([string]$Pattern, [string]$Label) {
    $result = Get-ChildItem -LiteralPath $output -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like $Pattern } |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $result) {
        throw "$Label non trovato in $output. Serve l'output PASS M71."
    }
    Write-Host "$Label acquisito: $($result.Name)"
    return $result
}

$m71 = Get-LatestAuditFile (
    "smartmoney-m71-adaptive-continuation-report-*.json"
) "Report M71 firmato"
$m67 = Get-LatestAuditFile (
    "smartmoney-m71-updated-m67-m70-report-*.json"
) "Report M67-M70 aggiornato"
$rpc = Get-LatestAuditFile (
    "smartmoney-m71-adaptive-rpc-evidence-*.json"
) "Evidenza RPC M71 aggiornata"

$arguments = @(
    $runner,
    "--confirmation", "RUN_M72_DEFINITIVE_DISCOVERY_ROTATION_READ_ONLY",
    "--output-dir", $output,
    "--m71-report", $m71.FullName,
    "--updated-m67-report", $m67.FullName,
    "--updated-rpc-evidence", $rpc.FullName
)

Set-Location $project
Write-Host "M72: rotazione definitiva candidati e piano discovery disarmato" -ForegroundColor Cyan
Write-Host "Solo JSON M71 firmati locali; nessuna rete/DB/Railway/Helius/Jupiter/POST/LIVE."
Write-Host "Output: $output"

$lines = @(& $python @arguments)
$exitCode = $LASTEXITCODE
$lines | ForEach-Object { Write-Host $_ }
if ($exitCode -ne 0) {
    throw "Runner M72 fallito con exit code $exitCode."
}
$joined = $lines -join "`n"
foreach ($marker in @(
    "M72_ROTATION=PASS",
    "ACTIVE_WALLETS_REVIEWED=6",
    "QUALIFIED_PENDING_SHORT_CANARY=0",
    "OBSERVE_ONLY=2",
    "RETIRED_FROM_PROMOTION=4",
    "RESEARCH_ONLY_LOCKED=1",
    "RERUN_M71_SAME_INPUTS=NO",
    "NEW_WALLET_DISCOVERY_REQUIRED=YES",
    "CONTROLLED_HELIUS_MAXIMUM_REQUESTS=6",
    "CONTROLLED_HELIUS_CREDIT_CAP=600",
    "CONTROLLED_HELIUS_RETRIES=0",
    "CONTROLLED_DISCOVERY_PLAN=PREPARED_DISARMED",
    "CONTROLLED_DISCOVERY_EXECUTION_AUTHORIZED=NO",
    "CONTROLLED_DISCOVERY_EXECUTION_PERFORMED=NO",
    "OFFICIAL_REALTIME_COUNTER=83_UNCHANGED",
    "NETWORK_REQUESTS=0",
    "HELIUS_REQUESTS=0",
    "HELIUS_CREDITS=0",
    "DATABASE_READS=0",
    "DATABASE_WRITES=0",
    "BACKEND_POSTS=0",
    "JUPITER_REQUESTS=0",
    "PAPER_ORDERS=0",
    "LIVE_ORDERS=0",
    "SIGNER_AUTHORIZED=NO",
    "MICRO_LIVE_EXECUTION_AUTHORIZED=NO",
    "M72_ROTATION_REPORT_FILE=",
    "M72_ACQUISITION_PLAN_FILE="
)) {
    if (-not $joined.Contains($marker)) {
        throw "Marker M72 reale mancante: $marker"
    }
}
Write-Host "M72_WINDOWS_WRAPPER=PASS" -ForegroundColor Green
