param(
    [string]$ProjectRoot = "C:\smartmoney-ai",
    [string]$AuditReport = "",
    [string]$RawEvidence = "",
    [string]$CanaryEvidence = "",
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "Repository non trovato: $ProjectRoot"
}
$project = (Resolve-Path -LiteralPath $ProjectRoot).Path
$python = Join-Path $project ".venv\Scripts\python.exe"
$runner = Join-Path $project "scripts\run_m65_gen4_definitive_wallet_gate.py"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Virtualenv Python non trovato: $python"
}
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "Runner M65 non installato: $runner"
}
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path ([Environment]::GetFolderPath("UserProfile")) (
        "Downloads\smartmoney-audits"
    )
}
$null = New-Item -ItemType Directory -Path $OutputDirectory -Force
$output = (Resolve-Path -LiteralPath $OutputDirectory).Path

if ([string]::IsNullOrWhiteSpace($AuditReport)) {
    $candidate = Get-ChildItem -LiteralPath $output -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "smartmoney-m64-83-plus-17-readonly-audit-*.json" } |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $candidate) {
        throw "Report M64 non trovato in $output. Eseguire prima l'audit M64."
    }
    $AuditReport = $candidate.FullName
}
if ([string]::IsNullOrWhiteSpace($RawEvidence)) {
    $candidate = Get-ChildItem -LiteralPath $output -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "smartmoney-m64-public-raw-evidence-*.json" } |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $candidate) {
        throw "Raw evidence M64 non trovato in $output."
    }
    $RawEvidence = $candidate.FullName
}

$arguments = @(
    $runner,
    "--confirmation", "RUN_M65_GEN4_DEFINITIVE_WALLET_QUALIFICATION_GATE",
    "--audit-report", $AuditReport,
    "--raw-evidence", $RawEvidence,
    "--output-dir", $output
)
if (-not [string]::IsNullOrWhiteSpace($CanaryEvidence)) {
    $arguments += @("--canary-evidence", $CanaryEvidence)
}

Write-Host "Esecuzione gate M65 locale e read-only"
$gateOutput = @(& $python @arguments)
$exitCode = $LASTEXITCODE
$gateOutput | ForEach-Object { Write-Host $_ }
$joined = $gateOutput -join "`n"
if ($exitCode -ne 0) { throw "Runner M65 fallito con exit code $exitCode." }
foreach ($marker in @(
    "GATE_EVALUATION=PASS",
    "OFFICIAL_REALTIME_TRADES=83",
    "RECONSTRUCTED_ANALYTIC_TRADES=17",
    "COMBINED_EQUIVALENT_SAMPLE=100",
    "MICRO_LIVE_EXECUTION_AUTHORIZED=NO",
    "AUTOMATIC_LIVE_ACTIVATION=NO",
    "HELIUS_REQUESTS=0",
    "DATABASE_WRITES=0",
    "BACKEND_POSTS=0"
)) {
    if ($joined -notmatch [regex]::Escape($marker)) {
        throw "Marker M65 mancante: $marker"
    }
}
Write-Host "M65_GATE_WRAPPER=PASS" -ForegroundColor Green
