param(
    [string]$ProjectRoot = "C:\smartmoney-ai",
    [string]$OutputDirectory = "",
    [string]$AuditReport = "",
    [string]$RawEvidence = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "Repository non trovato: $ProjectRoot"
}
$project = (Resolve-Path -LiteralPath $ProjectRoot).Path
$python = Join-Path $project ".venv\Scripts\python.exe"
$reissue = Join-Path $project "scripts\reissue_m64_hashfixed_audit_report.py"
$gate = Join-Path $project "RUN_M65_GEN4_DEFINITIVE_WALLET_GATE.ps1"
foreach ($required in @($python, $reissue, $gate)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "File richiesto non trovato: $required"
    }
}
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

if ([string]::IsNullOrWhiteSpace($AuditReport)) {
    $candidate = Get-ChildItem -LiteralPath $output -File -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -like "smartmoney-m64-83-plus-17-readonly-audit-*.json" -and
            $_.Name -notlike "*-hashfixed-*"
        } |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $candidate) {
        throw "Report M64 originale non trovato in $output."
    }
    $AuditReport = $candidate.FullName
}
$auditResolved = (Resolve-Path -LiteralPath $AuditReport).Path

if ([string]::IsNullOrWhiteSpace($RawEvidence)) {
    $rawFilename = & $python -c (
        "import json,sys; print(json.load(open(sys.argv[1], " +
        "encoding='utf-8-sig'))['artifacts']['raw_evidence_filename'])"
    ) $auditResolved
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($rawFilename)) {
        throw "Nome raw evidence non leggibile dal report M64."
    }
    $RawEvidence = Join-Path $output $rawFilename.Trim()
}
$rawResolved = (Resolve-Path -LiteralPath $RawEvidence).Path

Write-Host "[1/2] Riemissione deterministica report M64" -ForegroundColor Cyan
$reissueOutput = @(& $python $reissue `
    "--confirmation" "REISSUE_M64_ENRICHED_TRADE_HASHES_FROM_BOUND_RAW_EVIDENCE" `
    "--audit-report" $auditResolved `
    "--raw-evidence" $rawResolved `
    "--output-dir" $output)
$reissueExit = $LASTEXITCODE
$reissueOutput | ForEach-Object { Write-Host $_ }
if ($reissueExit -ne 0) {
    throw "Riemissione M64 fallita con exit code $reissueExit."
}
$reportLine = $reissueOutput |
    Where-Object { $_ -like "REISSUED_AUDIT_REPORT_FILE=*" } |
    Select-Object -Last 1
if ($null -eq $reportLine) {
    throw "Percorso del report M64 riemesso non trovato."
}
$fixedReport = $reportLine.Substring("REISSUED_AUDIT_REPORT_FILE=".Length)
if (-not (Test-Path -LiteralPath $fixedReport -PathType Leaf)) {
    throw "Report M64 riemesso non trovato: $fixedReport"
}

Write-Host "[2/2] Gate definitivo M65 sul report corretto" -ForegroundColor Cyan
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $gate `
    -ProjectRoot $project `
    -AuditReport $fixedReport `
    -RawEvidence $rawResolved `
    -OutputDirectory $output
if ($LASTEXITCODE -ne 0) {
    throw "Gate M65 fallito dopo la correzione hash."
}

Write-Host "M65_HOTFIX1_REISSUE_AND_GATE=PASS" -ForegroundColor Green
Write-Host "ECONOMICS_MODIFIED=NO"
Write-Host "OFFICIAL_COUNTER_MUTATED=NO"
Write-Host "RECOVERY_COUNTS_AS_REALTIME_PROOF=NO"
Write-Host "NETWORK_REQUESTS=0"
Write-Host "HELIUS_REQUESTS=0"
Write-Host "DATABASE_WRITES=0"
Write-Host "BACKEND_POSTS=0"
Write-Host "MICRO_LIVE_EXECUTION_AUTHORIZED=NO"
