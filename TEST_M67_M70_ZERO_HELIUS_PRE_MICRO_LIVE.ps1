param(
    [string]$ProjectRoot = "C:\smartmoney-ai"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "Repository non trovato: $ProjectRoot"
}
$project = (Resolve-Path -LiteralPath $ProjectRoot).Path
$python = Join-Path $project ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Virtualenv Python non trovato: $python"
}
$fixture = Join-Path $project "tests\fixtures\m67_m70_zero_helius_pre_micro_live.json"
$temporaryOutput = Join-Path ([System.IO.Path]::GetTempPath()) (
    "smartmoney-m67-m70-offline-" + [Guid]::NewGuid().ToString("N")
)
$null = New-Item -ItemType Directory -Path $temporaryOutput -Force

try {
    Set-Location $project
    & $python -m compileall backend scripts tests
    if ($LASTEXITCODE -ne 0) { throw "Compileall M67-M70 fallito." }

    & $python scripts\verify_m67_m70_zero_helius_pre_micro_live.py
    if ($LASTEXITCODE -ne 0) { throw "Verifier M67-M70 fallito." }

    & $python -m pytest tests\test_m67_m70_zero_helius_pre_micro_live.py -q
    if ($LASTEXITCODE -ne 0) { throw "Test mirati M67-M70 falliti." }

    $lines = @(& $python scripts\run_m67_m70_zero_helius_pre_micro_live.py `
        --confirmation RUN_M67_M70_ZERO_HELIUS_READ_ONLY `
        --output-dir $temporaryOutput `
        --fixture $fixture)
    $exitCode = $LASTEXITCODE
    $lines | ForEach-Object { Write-Host $_ }
    if ($exitCode -ne 0) { throw "Replay fixture M67-M70 fallito." }
    $joined = $lines -join "`n"
    foreach ($marker in @(
        "M67_M70_EVALUATION=PASS",
        "PUBLIC_RPC_REQUESTS=0",
        "HELIUS_REQUESTS=0",
        "DATABASE_WRITES=0",
        "BACKEND_POSTS=0",
        "JUPITER_REQUESTS=0",
        "PAPER_ORDERS=0",
        "LIVE_ORDERS=0",
        "PRE_MICRO_LIVE_FOUNDATION=PREPARED_DISARMED"
    )) {
        if (-not $joined.Contains($marker)) {
            throw "Marker fixture M67-M70 mancante: $marker"
        }
    }
    Write-Host "M67_M70_TARGETED_TESTS=PASS" -ForegroundColor Green
}
finally {
    if (Test-Path -LiteralPath $temporaryOutput) {
        Remove-Item -LiteralPath $temporaryOutput -Recurse -Force
    }
}
