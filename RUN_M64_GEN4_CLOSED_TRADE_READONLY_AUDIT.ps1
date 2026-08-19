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
$python = Join-Path $project ".venv\Scripts\python.exe"
$runner = Join-Path $project "scripts\run_m64_gen4_closed_trade_readonly_audit.py"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python virtualenv non trovato: $python"
}
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "Runner M64 non installato: $runner"
}

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $userProfile = [Environment]::GetFolderPath("UserProfile")
    $OutputDirectory = Join-Path $userProfile "Downloads\smartmoney-audits"
}
$null = New-Item -ItemType Directory -Path $OutputDirectory -Force
$output = (Resolve-Path -LiteralPath $OutputDirectory).Path
if ($output.StartsWith($project, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "La cartella audit deve restare fuori dal repository Git."
}

$auditArguments = @(
    $runner,
    "--confirmation", "RUN_M64_GEN4_CLOSED_TRADE_READONLY_AUDIT",
    "--output-dir", $output,
    "--rpc-url", $PublicRpcUrl,
    "--max-signatures", [string]$MaximumSignatures,
    "--target-reconstructed-trades", "17"
)

Set-Location $project
Write-Host "M64: audit read-only 83 + round trip pubblici" -ForegroundColor Cyan
Write-Host "Output: $output"
Write-Host "Il comando non usa Helius e non esegue POST al backend."

$lines = @()
if (-not [string]::IsNullOrWhiteSpace($env:DATABASE_PUBLIC_URL)) {
    $lines = @(& $python @auditArguments)
    $exitCode = $LASTEXITCODE
}
else {
    $railwayCommand = Get-Command railway.cmd -ErrorAction SilentlyContinue
    if ($null -eq $railwayCommand) {
        throw (
            "DATABASE_PUBLIC_URL non presente e railway.cmd non trovato. " +
            "L'audit e stato interrotto senza fallback a DATABASE_URL."
        )
    }
    $railwayArguments = @(
        "run",
        "--service", "Postgres",
        "--environment", "production",
        "--no-local",
        $python
    ) + $auditArguments

    # Railway puo scrivere un avviso di aggiornamento su stderr. Manteniamo
    # stdout e stderr separati e validiamo sia exit code sia marker Python.
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
    throw "Runner M64 fallito con exit code $exitCode."
}
$joined = $lines -join "`n"
$requiredMarkers = @(
    "AUDIT=PASS",
    "OFFICIAL_REALTIME_TRADES=83",
    "HELIUS_REQUESTS=0",
    "DATABASE_WRITES=0",
    "BACKEND_POSTS=0",
    "OFFICIAL_COUNTER_MUTATED=NO",
    "RECOVERY_COUNTS_AS_REALTIME_PROOF=NO",
    "HISTORICAL_JUPITER_QUOTES=UNAVAILABLE_NOT_INVENTED"
)
foreach ($marker in $requiredMarkers) {
    if (-not $joined.Contains($marker)) {
        throw "Marker audit reale mancante: $marker"
    }
}
if ($joined -notmatch "RECONSTRUCTED_CLOSED_TRADES=([0-9]+)") {
    throw "Contatore trade ricostruiti assente."
}
$reconstructed = [int]$matches[1]
if ($joined -notmatch "COMBINED_EQUIVALENT_SAMPLE=([0-9]+)") {
    throw "Contatore campione combinato assente."
}
$combined = [int]$matches[1]
if ($combined -ne (83 + $reconstructed)) {
    throw "Campione combinato incoerente: 83 + $reconstructed != $combined."
}

Write-Host "M64 AUDIT COMPLETATO E VALIDATO" -ForegroundColor Green
Write-Host "83 ufficiali restano separati; ricostruiti=$reconstructed; equivalente=$combined."
