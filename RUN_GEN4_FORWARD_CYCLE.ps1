param(
    [string]$CampaignId = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo = "C:\smartmoney-ai"
$python = Join-Path $repo ".venv\Scripts\python.exe"
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$output = Join-Path $HOME "Downloads\smartmoney-gen4-forward-cycle-$timestamp.json"

if (-not (Test-Path -LiteralPath $python)) { throw "Virtual environment non trovato: $python" }
Set-Location $repo

$previous = $env:CANONICAL_PARSER_GEN4_FORWARD_ENABLED
$env:CANONICAL_PARSER_GEN4_FORWARD_ENABLED = "true"
try {
    $args = @(
        "scripts/run_gen4_forward_shadow.py",
        "cycle",
        "--confirmation", "RUN_GEN4_STRICT_FORWARD_CYCLE",
        "--output", $output
    )
    if (-not [string]::IsNullOrWhiteSpace($CampaignId)) {
        $args += @("--campaign-id", $CampaignId.Trim())
    }
    & $python @args
    if ($LASTEXITCODE -ne 0) { throw "Ciclo Gen4 forward non riuscito." }
} finally {
    if ($null -eq $previous) {
        Remove-Item Env:CANONICAL_PARSER_GEN4_FORWARD_ENABLED -ErrorAction SilentlyContinue
    } else {
        $env:CANONICAL_PARSER_GEN4_FORWARD_ENABLED = $previous
    }
}
Write-Host "Report: $output" -ForegroundColor Green
Write-Host "Nessun Helius, paper, signer o LIVE." -ForegroundColor Green
