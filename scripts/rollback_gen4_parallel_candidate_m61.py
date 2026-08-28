from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_URL = "https://smartmoney-ai-production-0042.up.railway.app"
STATUS_PATH = "/integrity/parser-gen4-copyability/status?recent_limit=5"
STOP_PATH = "/integrity/parser-gen4-copyability/stop"
CONFIGURE_PATH = "/integrity/parser-gen4-copyability/webhook/configure"
WEBHOOK_PATH = "/integrity/parser-gen4-copyability/webhook/helius"
HELIUS_WEBHOOK_API = "https://api-mainnet.helius-rpc.com/v0/webhooks"
EXPECTED_CONFIRMATION = "ROLLBACK_M61_CANDIDATE_ONLY"
STOP_CONFIRMATION = "STOP_GEN4_REALTIME_COPYABILITY"
CONFIGURE_CONFIRMATION = "CONFIGURE_GEN4_COPYABILITY_WEBHOOK"
PRIMARY_CAMPAIGN_ID = "89026d62-1e4e-452b-b0bf-8a5e3dd373e4"
PRIMARY_WALLETS = {
    "FsKYLBwxLQk5YMNSPYQcqceW6o8tJGF7U1aBHyEvGAyE",
    "2ZwYWRaQR7X3zcD7VX8u4Ke8znPQuKrVpRnU3Tp6UH7S",
}
CANDIDATE_WALLET = "Bs34SxJUSjUntbsWDEZrFKEcCdJfSuF9KiwtFdJ1Tfsd"


class RollbackError(RuntimeError):
    pass


def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def require(values: dict[str, str], name: str) -> str:
    value = str(os.environ.get(name) or values.get(name) or "").strip()
    if not value:
        raise RollbackError(f"Valore richiesto mancante: {name}")
    return value


def backend_request(
    client: httpx.Client,
    method: str,
    path: str,
    automation_key: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = client.request(
        method,
        f"{BACKEND_URL}{path}",
        headers={
            "X-Automation-Key": automation_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        json=payload,
    )
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.is_error:
        raise RollbackError(
            f"Backend {method} {path} HTTP {response.status_code}: "
            f"{str(body.get('detail') if isinstance(body, dict) else '')[:300]}"
        )
    if not isinstance(body, dict):
        raise RollbackError("Risposta backend non valida")
    return body


def helius_request(
    client: httpx.Client,
    method: str,
    url: str,
    helius_key: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    response = client.request(
        method,
        url,
        params={"api-key": helius_key},
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        json=payload,
    )
    try:
        body = response.json()
    except ValueError:
        body = None
    if response.is_error:
        raise RollbackError(f"Helius {method} HTTP {response.status_code}")
    return body


def webhook_id(item: dict[str, Any]) -> str:
    return str(item.get("webhookID") or item.get("webhookId") or "").strip()


def main() -> int:
    confirmation = str(os.environ.get("M61_ROLLBACK_CONFIRMATION") or "").strip()
    if confirmation != EXPECTED_CONFIRMATION:
        raise RollbackError(f"Conferma richiesta: {EXPECTED_CONFIRMATION}")

    dotenv = read_dotenv(PROJECT_ROOT / ".env")
    helius_key = require(dotenv, "HELIUS_API_KEY")
    automation_key = require(dotenv, "AUTOMATION_API_KEY")
    webhook_secret = require(
        dotenv,
        "CANONICAL_PARSER_GEN4_COPYABILITY_WEBHOOK_SECRET",
    )
    target_url = f"{BACKEND_URL}{WEBHOOK_PATH}"

    print("M61_SAFE_OPERATIONAL_ROLLBACK=STARTED")
    print("MODE=STOP_CANDIDATE_PRESERVE_EVIDENCE")
    print("PRIMARY_CAMPAIGN_MODIFIED=NO")
    print("DATABASE_ROWS_DELETED=NO")
    print("ALEMBIC_DOWNGRADE=NO")
    print("GIT_REVERT=NO")
    print("SECRETS=REDACTED")

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        before = backend_request(client, "GET", STATUS_PATH, automation_key)
        campaigns = [
            item for item in (before.get("active_campaigns") or []) if isinstance(item, dict)
        ]
        primary = next(
            (item for item in campaigns if item.get("campaign_role") == "PRIMARY_FORWARD"),
            None,
        )
        if primary is None:
            raise RollbackError("Campagna primaria non trovata")
        if str(primary.get("campaign_id")) != PRIMARY_CAMPAIGN_ID:
            raise RollbackError("Campaign ID primario inatteso")
        if set(primary.get("frozen_wallets") or []) != PRIMARY_WALLETS:
            raise RollbackError("Wallet primari inattesi")
        primary_anchor = str(primary.get("anchor_at") or "")
        primary_counts = dict(primary.get("counts") or {})

        candidates = [
            item
            for item in campaigns
            if item.get("campaign_role") == "QUALIFIED_CANDIDATE"
        ]
        unexpected = [
            item
            for item in candidates
            if set(item.get("frozen_wallets") or []) != {CANDIDATE_WALLET}
        ]
        if unexpected:
            raise RollbackError("Esiste una campagna candidata inattesa; rollback fermato")

        stopped_ids: list[str] = []
        for candidate in candidates:
            candidate_id = str(candidate.get("campaign_id") or "").strip()
            if not candidate_id:
                raise RollbackError("Candidate campaign ID mancante")
            backend_request(
                client,
                "POST",
                STOP_PATH,
                automation_key,
                {
                    "campaign_id": candidate_id,
                    "confirmation": STOP_CONFIRMATION,
                    "observed_at": None,
                },
            )
            stopped_ids.append(candidate_id)

        webhooks_raw = helius_request(client, "GET", HELIUS_WEBHOOK_API, helius_key)
        webhooks = webhooks_raw if isinstance(webhooks_raw, list) else []
        exact = next(
            (
                item
                for item in webhooks
                if isinstance(item, dict)
                and str(item.get("webhookURL") or "").rstrip("/")
                == target_url.rstrip("/")
            ),
            None,
        )
        if exact is None:
            raise RollbackError("Webhook Gen4 esistente non trovato")
        identifier = webhook_id(exact)
        if not identifier:
            raise RollbackError("Webhook Gen4 privo di ID")
        # GET /v0/webhooks is a summary view and may omit accountAddresses.
        # Resolve the exact target there, then use GET-by-ID as the authoritative
        # source for monitored addresses and webhook attributes.
        detail = helius_request(
            client,
            "GET",
            f"{HELIUS_WEBHOOK_API}/{identifier}",
            helius_key,
        )
        if not isinstance(detail, dict):
            raise RollbackError("Webhook Gen4 non leggibile per ID")
        if webhook_id(detail) != identifier:
            raise RollbackError("Webhook Gen4 per ID non coincide")
        if str(detail.get("webhookURL") or "").rstrip("/") != target_url.rstrip("/"):
            raise RollbackError("Webhook Gen4 per ID punta a un URL inatteso")
        if str(detail.get("webhookType") or "").lower() != "raw":
            raise RollbackError("Webhook Gen4 per ID non è RAW")
        if not bool(detail.get("active")):
            raise RollbackError("Webhook Gen4 per ID non è attivo")
        transaction_types = detail.get("transactionTypes")
        if not isinstance(transaction_types, list) or not transaction_types:
            raise RollbackError("Webhook Gen4 RAW privo di transactionTypes preservabili")
        auth_header = str(detail.get("authHeader") or webhook_secret).strip()
        if not auth_header:
            raise RollbackError("Webhook Gen4 RAW privo di authHeader preservabile")

        current_addresses = {
            str(value).strip()
            for value in (detail.get("accountAddresses") or [])
            if str(value).strip()
        }
        allowed = (PRIMARY_WALLETS, PRIMARY_WALLETS | {CANDIDATE_WALLET})
        if current_addresses not in allowed:
            raise RollbackError("Webhook Gen4 contiene indirizzi inattesi")

        if current_addresses != PRIMARY_WALLETS:
            helius_request(
                client,
                "PUT",
                f"{HELIUS_WEBHOOK_API}/{identifier}",
                helius_key,
                {
                    "webhookURL": target_url,
                    "transactionTypes": list(transaction_types),
                    "accountAddresses": sorted(PRIMARY_WALLETS),
                    "webhookType": "raw",
                    "authHeader": auth_header,
                    "encoding": str(detail.get("encoding") or "jsonParsed"),
                    "txnStatus": str(detail.get("txnStatus") or "success"),
                },
            )
        backend_request(
            client,
            "POST",
            CONFIGURE_PATH,
            automation_key,
            {
                "campaign_id": PRIMARY_CAMPAIGN_ID,
                "confirmation": CONFIGURE_CONFIRMATION,
                "webhook_id": identifier,
                "webhook_url": target_url,
                "active": True,
                "observed_at": None,
            },
        )

        verified = helius_request(
            client,
            "GET",
            f"{HELIUS_WEBHOOK_API}/{identifier}",
            helius_key,
        )
        if not isinstance(verified, dict) or not bool(verified.get("active")):
            raise RollbackError("Webhook primario non attivo dopo rollback")
        if set(verified.get("accountAddresses") or []) != PRIMARY_WALLETS:
            raise RollbackError("Webhook non ripristinato ai due wallet primari")
        if verified.get("transactionTypes") != transaction_types:
            raise RollbackError("Webhook rollback non ha preservato transactionTypes")

        after = backend_request(client, "GET", STATUS_PATH, automation_key)
        after_campaigns = [
            item for item in (after.get("active_campaigns") or []) if isinstance(item, dict)
        ]
        if int(after.get("active_campaign_count") or 0) != 1 or len(after_campaigns) != 1:
            raise RollbackError("Dopo rollback deve restare una sola campagna attiva")
        primary_after = after_campaigns[0]
        if primary_after.get("campaign_role") != "PRIMARY_FORWARD":
            raise RollbackError("La campagna attiva residua non è la primaria")
        if str(primary_after.get("campaign_id")) != PRIMARY_CAMPAIGN_ID:
            raise RollbackError("Campaign ID primario cambiato")
        if str(primary_after.get("anchor_at") or "") != primary_anchor:
            raise RollbackError("Anchor primario cambiato")
        if set(primary_after.get("frozen_wallets") or []) != PRIMARY_WALLETS:
            raise RollbackError("Wallet primari cambiati")
        counts_after = dict(primary_after.get("counts") or {})
        for key, before_value in primary_counts.items():
            if int(counts_after.get(key) or 0) < int(before_value or 0):
                raise RollbackError(f"Contatore primario regredito: {key}")

        safety = after.get("safety") or {}
        required_zero = {
            "signer_access": False,
            "signed_transactions": 0,
            "submitted_transactions": 0,
            "paper_orders_created": 0,
            "live_orders_created": 0,
            "automatic_live_activation": False,
        }
        for key, expected in required_zero.items():
            if safety.get(key) != expected:
                raise RollbackError(f"Guardia sicurezza non valida: {key}")

    report = PROJECT_ROOT / ".smartmoney-backups" / (
        "M61_SAFE_ROLLBACK_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json"
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "mode": "STOP_CANDIDATE_PRESERVE_EVIDENCE",
                "stopped_candidate_campaign_ids": stopped_ids,
                "primary_campaign_id": PRIMARY_CAMPAIGN_ID,
                "primary_anchor": primary_anchor,
                "primary_wallets": sorted(PRIMARY_WALLETS),
                "webhook_wallet_count": 2,
                "database_rows_deleted": False,
                "alembic_downgrade": False,
                "git_revert": False,
                "paper_enabled": False,
                "live_enabled": False,
                "secrets_in_report": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print("M61_SAFE_OPERATIONAL_ROLLBACK=PASS")
    print("CANDIDATE_CAMPAIGNS_STOPPED=" + str(len(stopped_ids)))
    print("ACTIVE_COPYABILITY_CAMPAIGNS=1")
    print("PRIMARY_CAMPAIGN_PRESERVED=YES")
    print("HELIUS_RAW_WEBHOOK_WALLETS=2_PRIMARY_ONLY")
    print("CANDIDATE_EVIDENCE_PRESERVED=YES")
    print("NO_SIGNER_NO_SIGNATURE_NO_SUBMISSION_NO_PAPER_NO_LIVE")
    print(f"REPORT={report}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("M61_SAFE_OPERATIONAL_ROLLBACK=FAIL", file=sys.stderr)
        print(f"ERROR_TYPE={type(exc).__name__}", file=sys.stderr)
        print(f"ERROR_MESSAGE={str(exc)[:500]}", file=sys.stderr)
        raise SystemExit(1)
