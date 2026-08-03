param(
    [string]$ProjectRoot = "C:\smartmoney-ai",
    [switch]$DropEmptyLocalSchema
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $ProjectRoot
$python = ".\.venv\Scripts\python.exe"

Write-Host "ROLLBACK SICURO M58-M60" -ForegroundColor Yellow
Write-Host "Disabilito prima webhook e runtime; l'evidenza viene conservata." -ForegroundColor Yellow

$envValues = @{}
Get-Content .env -Encoding UTF8 | ForEach-Object {
    if ($_ -match '^\s*([^#=]+?)\s*=\s*(.*)$') {
        $envValues[$matches[1].Trim()] = $matches[2].Trim().Trim('"').Trim("'")
    }
}

$heliusKey = $envValues['HELIUS_API_KEY']
if (-not [string]::IsNullOrWhiteSpace($heliusKey)) {
    $env:ROLLBACK_HELIUS_API_KEY = $heliusKey
    $disableCode = @'
import os
import httpx

key = os.environ["ROLLBACK_HELIUS_API_KEY"]
base = "https://api-mainnet.helius-rpc.com/v0/webhooks"
target = "https://smartmoney-ai-production-0042.up.railway.app/integrity/parser-gen4-copyability/webhook/helius"
with httpx.Client(timeout=30.0) as client:
    response = client.get(base, params={"api-key": key})
    response.raise_for_status()
    matches = [item for item in response.json() if str(item.get("webhookURL") or "").rstrip("/") == target.rstrip("/")]
    for item in matches:
        webhook_id = item.get("webhookID") or item.get("webhookId")
        result = client.patch(f"{base}/{webhook_id}", params={"api-key": key}, json={"active": False})
        result.raise_for_status()
print(f"HELIUS_WEBHOOKS_DISABLED={len(matches)}")
'@
    try {
        & $python -c $disableCode
        if ($LASTEXITCODE -ne 0) { throw "Disabilitazione webhook fallita." }
    }
    finally {
        Remove-Item Env:ROLLBACK_HELIUS_API_KEY -ErrorAction SilentlyContinue
    }
}
else {
    Write-Host "HELIUS_API_KEY locale assente: disabilita manualmente il webhook nel pannello Helius." -ForegroundColor Yellow
}

railway variable set "CANONICAL_PARSER_GEN4_COPYABILITY_ENABLED=false" `
    --skip-deploys --service smartmoney-ai --environment production
if ($LASTEXITCODE -ne 0) { throw "Impossibile disabilitare runtime Railway." }

railway variable set "CANONICAL_PARSER_GEN4_COPYABILITY_AUTOSTART=false" `
    --skip-deploys --service smartmoney-ai --environment production
if ($LASTEXITCODE -ne 0) { throw "Impossibile disabilitare autostart Railway." }

railway up --service smartmoney-ai --environment production --yes `
    --message "rollback-safe disable Gen4 M58-M60"
if ($LASTEXITCODE -ne 0) { throw "Redeploy backend fail-safe non riuscito." }

# Il codice M58-M60 resta installato quando esiste evidenza: rimuovere la
# migration mentre il database è alla head b6 renderebbe il pre-deploy Alembic
# non riproducibile. Il rollback operativo corretto è disabilitare webhook e
# runtime, conservando schema e dati.

if ($DropEmptyLocalSchema) {
    & $python -m alembic downgrade a5e7c1d4b926
    if ($LASTEXITCODE -ne 0) {
        throw "Downgrade rifiutato: probabilmente esiste evidenza M58-M60. È corretto conservarla."
    }
}

Write-Host "ROLLBACK SICURO M58-M60: COMPLETATO" -ForegroundColor Green
Write-Host "Webhook e runtime disabilitati; database/evidenza preservati." -ForegroundColor Green
