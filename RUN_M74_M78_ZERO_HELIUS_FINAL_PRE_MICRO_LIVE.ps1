param(
    [string]$ProjectRoot = "C:\smartmoney-ai",
    [string]$OutputDirectory = ""
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) { throw "Repository non trovato: $ProjectRoot" }
$project=(Resolve-Path -LiteralPath $ProjectRoot).Path
$python=Join-Path $project ".venv\Scripts\python.exe"
$runner=Join-Path $project "scripts\run_m74_m78_zero_helius_final_pre_micro_live.py"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Virtualenv Python non trovato: $python" }
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) { throw "Runner M74-M78 non installato: $runner" }
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) { $OutputDirectory=Join-Path ([Environment]::GetFolderPath("UserProfile")) "Downloads\smartmoney-audits" }
$null=New-Item -ItemType Directory -Path $OutputDirectory -Force
$output=(Resolve-Path -LiteralPath $OutputDirectory).Path
if ($output.StartsWith($project,[System.StringComparison]::OrdinalIgnoreCase)) { throw "Output M74-M78 deve restare fuori dal repository." }
function Latest([string]$Pattern,[string]$Label) {
  $f=Get-ChildItem -LiteralPath $output -File -ErrorAction SilentlyContinue | Where-Object {$_.Name -like $Pattern} | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
  if ($null -eq $f) { throw "$Label non trovato in $output. Serve l'output PASS M72." }
  Write-Host "$Label acquisito: $($f.Name)"; return $f
}
$m72=Latest "smartmoney-m72-definitive-discovery-rotation-report-*.json" "Report M72 firmato"
$plan=Latest "smartmoney-m72-controlled-new-wallet-acquisition-plan-disarmed-*.json" "Piano M72 firmato"
Set-Location $project
Write-Host "M74-M78: preparazione finale pre-Micro-Live ZERO NETWORK" -ForegroundColor Cyan
Write-Host "Nessun Helius, RPC, DB, Railway, Jupiter, signer, paper o LIVE."
$lines=@(& $python $runner --mode prepare --confirmation "PREPARE_M74_M78_ZERO_HELIUS_FINAL_PRE_MICRO_LIVE" --output-dir $output --m72-report $m72.FullName --m72-plan $plan.FullName)
$code=$LASTEXITCODE; $lines | ForEach-Object {Write-Host $_}
if ($code -ne 0) { throw "Runner M74-M78 fallito con exit code $code." }
$joined=$lines -join "`n"
foreach($marker in @(
 "M74_M78=PASS","MODE=PREPARE","NETWORK_REQUESTS=0","PUBLIC_RPC_REQUESTS=0","HELIUS_REQUESTS=0","HELIUS_CREDITS=0",
 "DATABASE_READS=0","DATABASE_WRITES=0","JUPITER_REQUESTS=0","PAPER_ORDERS=0","LIVE_ORDERS=0","SIGNED_TRANSACTIONS=0","SUBMITTED_TRANSACTIONS=0",
 "SIGNER_ACCESS=NO","AUTOMATIC_LIVE_ACTIVATION=NO","MICRO_LIVE_EXECUTION_AUTHORIZED=NO",
 "M74_CANDIDATE_ADMISSION=IMPLEMENTED","M75_SHORT_CANARY=IMPLEMENTED_DISARMED","M76_MULTI_WALLET_CONSENSUS=IMPLEMENTED_DISARMED",
 "M77_MICRO_LIVE_ENVELOPE=IMPLEMENTED_DISARMED_REUSES_M35","M78_FINAL_TRANSITION=IMPLEMENTED_AWAITING_REAL_EVIDENCE","M74_M78_REPORT_FILE="
)) { if (-not $joined.Contains($marker)) { throw "Marker M74-M78 mancante: $marker" } }
Write-Host "M74_M78_WINDOWS_WRAPPER=PASS" -ForegroundColor Green
