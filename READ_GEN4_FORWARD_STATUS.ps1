param(
    [string]$CampaignId = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo = "C:\smartmoney-ai"
$python = Join-Path $repo ".venv\Scripts\python.exe"
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$output = Join-Path $HOME "Downloads\smartmoney-gen4-forward-status-$timestamp.json"

if (-not (Test-Path -LiteralPath $python)) { throw "Virtual environment non trovato: $python" }
Set-Location $repo
$args = @("scripts/run_gen4_forward_shadow.py", "status", "--output", $output)
if (-not [string]::IsNullOrWhiteSpace($CampaignId)) {
    $args += @("--campaign-id", $CampaignId.Trim())
}
& $python @args
if ($LASTEXITCODE -ne 0) { throw "Lettura stato Gen4 forward non riuscita." }
Write-Host "Report: $output" -ForegroundColor Green
