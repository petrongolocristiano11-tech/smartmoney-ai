param(
    [string[]]$CandidateWallets = @(),
    [string]$Note = "M52-M53 strict forward shadow campaign"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo = "C:\smartmoney-ai"
$python = Join-Path $repo ".venv\Scripts\python.exe"
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$output = Join-Path $HOME "Downloads\smartmoney-gen4-forward-start-$timestamp.json"

if (-not (Test-Path -LiteralPath $python)) { throw "Virtual environment non trovato: $python" }
Set-Location $repo

$previous = $env:CANONICAL_PARSER_GEN4_FORWARD_ENABLED
$env:CANONICAL_PARSER_GEN4_FORWARD_ENABLED = "true"
try {
    $args = @(
        "scripts/run_gen4_forward_shadow.py",
        "start",
        "--confirmation", "START_GEN4_STRICT_FORWARD_SHADOW",
        "--actor-label", "LOCAL_GEN4_FORWARD_SHADOW",
        "--note", $Note,
        "--output", $output
    )
    foreach ($wallet in $CandidateWallets) {
        if (-not [string]::IsNullOrWhiteSpace($wallet)) {
            $args += @("--candidate-wallet", $wallet.Trim())
        }
    }
    & $python @args
    if ($LASTEXITCODE -ne 0) { throw "Avvio campagna Gen4 forward non riuscito." }
} finally {
    if ($null -eq $previous) {
        Remove-Item Env:CANONICAL_PARSER_GEN4_FORWARD_ENABLED -ErrorAction SilentlyContinue
    } else {
        $env:CANONICAL_PARSER_GEN4_FORWARD_ENABLED = $previous
    }
}
Write-Host "Report: $output" -ForegroundColor Green
