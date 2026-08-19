param(
    [Parameter(Mandatory=$true)][string]$M73Report,
    [Parameter(Mandatory=$true)][string]$CanaryEvidence,
    [Parameter(Mandatory=$true)][string]$IndependenceEvidence,
    [string]$ProjectRoot = "C:\smartmoney-ai",
    [string]$OutputDirectory = ""
)
$ErrorActionPreference="Stop"; Set-StrictMode -Version Latest
$project=(Resolve-Path -LiteralPath $ProjectRoot).Path
$python=Join-Path $project ".venv\Scripts\python.exe"
$runner=Join-Path $project "scripts\run_m74_m78_zero_helius_final_pre_micro_live.py"
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) { $OutputDirectory=Join-Path ([Environment]::GetFolderPath("UserProfile")) "Downloads\smartmoney-audits" }
$null=New-Item -ItemType Directory -Path $OutputDirectory -Force
$output=(Resolve-Path -LiteralPath $OutputDirectory).Path
function Latest([string]$Pattern,[string]$Label) {
  $f=Get-ChildItem -LiteralPath $output -File -ErrorAction SilentlyContinue | Where-Object {$_.Name -like $Pattern} | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
  if ($null -eq $f) { throw "$Label non trovato in $output." }; return $f
}
$m72=Latest "smartmoney-m72-definitive-discovery-rotation-report-*.json" "Report M72"
$plan=Latest "smartmoney-m72-controlled-new-wallet-acquisition-plan-disarmed-*.json" "Piano M72"
foreach($evidencePath in @($M73Report,$CanaryEvidence,$IndependenceEvidence)) {
  if (-not (Test-Path -LiteralPath $evidencePath -PathType Leaf)) { throw "File evidenza non trovato: $evidencePath" }
}
Set-Location $project
& $python $runner --mode evaluate --confirmation "EVALUATE_M74_M78_OFFLINE_POST_DISCOVERY_EVIDENCE" --output-dir $output --m72-report $m72.FullName --m72-plan $plan.FullName --m73-report $M73Report --canary-evidence $CanaryEvidence --independence-evidence $IndependenceEvidence
if ($LASTEXITCODE -ne 0) { throw "Valutazione post-discovery M74-M78 fallita." }
Write-Host "M74_M78_POST_DISCOVERY_EVALUATION_WRAPPER=PASS" -ForegroundColor Green
