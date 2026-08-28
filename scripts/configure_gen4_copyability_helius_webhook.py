from __future__ import annotations

import json
import os
import sys
from typing import Any

import httpx

HELIUS_WEBHOOK_API = "https://api-mainnet.helius-rpc.com/v0/webhooks"
WEBHOOK_PATH = "/integrity/parser-gen4-copyability/webhook/helius"
START_CONFIRMATION = "START_GEN4_REALTIME_COPYABILITY"
CONFIGURE_CONFIRMATION = "CONFIGURE_GEN4_COPYABILITY_WEBHOOK"
REPLACE_CONFIRMATION = "REPLACE_EXISTING_HELIUS_WEBHOOK"


class SetupError(RuntimeError):
    pass


def required_env(name: str) -> str:
    value = str(os.getenv(name) or "").strip()
    if not value:
        raise SetupError(f"Variabile richiesta assente: {name}")
    return value


def safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text[:1000]}


def request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
) -> Any:
    try:
        response = client.request(
            method,
            url,
            params=params,
            headers=headers,
            json=payload,
        )
    except httpx.TimeoutException as exc:
        raise SetupError(f"Timeout {method} verso il provider.") from None
    except httpx.HTTPError as exc:
        raise SetupError(f"Errore di rete {method} verso il provider.") from None
    body = safe_json(response)
    if response.is_error:
        # Never include the request URL because the Helius API key is a query parameter.
        raise SetupError(
            f"HTTP {response.status_code} durante {method}: "
            f"{json.dumps(body, ensure_ascii=False)[:1000]}"
        )
    return body


def backend_request(
    client: httpx.Client,
    method: str,
    backend_url: str,
    path: str,
    automation_key: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    return request_json(
        client,
        method,
        f"{backend_url.rstrip('/')}{path}",
        headers={
            "X-Automation-Key": automation_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        payload=payload,
    )


def webhook_id(item: dict[str, Any]) -> str:
    return str(item.get("webhookID") or item.get("webhookId") or "").strip()


def main() -> None:
    helius_key = required_env("HELIUS_API_KEY")
    webhook_secret = required_env("GEN4_WEBHOOK_SECRET")
    backend_url = required_env("GEN4_BACKEND_URL").rstrip("/")
    automation_key = required_env("AUTOMATION_API_KEY")
    replace_confirmation = str(os.getenv("GEN4_REPLACE_WEBHOOK_CONFIRMATION") or "").strip()
    expected_exclusive_wallet = str(
        os.getenv("GEN4_EXPECT_EXCLUSIVE_WALLET") or ""
    ).strip()
    target_url = f"{backend_url}{WEBHOOK_PATH}"

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        status = backend_request(
            client,
            "GET",
            backend_url,
            "/integrity/parser-gen4-copyability/status?recent_limit=1",
            automation_key,
        )
        campaign = status.get("campaign") if isinstance(status, dict) else None
        if campaign is None:
            started = backend_request(
                client,
                "POST",
                backend_url,
                "/integrity/parser-gen4-copyability/start",
                automation_key,
                {
                    "confirmation": START_CONFIRMATION,
                    "actor_label": "RAILWAY_M58_M60_INSTALLER",
                    "note": (
                        "Seconda campagna indipendente: real-time copyability con "
                        "Helius raw webhook e Jupiter unsigned shadow build."
                    ),
                },
            )
            campaign = started

        # M61 keeps the primary M58-M60 campaign intact and may add isolated
        # qualified-candidate campaigns. One exact Gen4 Raw Webhook monitors
        # the union of all ACTIVE campaign wallets; the backend routes each
        # receipt to its owning campaign. Before M61, this naturally reduces
        # to the original single primary campaign with two frozen wallets.
        active_campaigns = (
            status.get("active_campaigns")
            if isinstance(status, dict)
            else None
        )
        if not isinstance(active_campaigns, list) or not active_campaigns:
            active_campaigns = [campaign]

        campaigns: list[dict[str, Any]] = []
        wallet_owners: dict[str, str] = {}
        for item in active_campaigns:
            if not isinstance(item, dict):
                continue
            campaign_id = str(item.get("campaign_id") or "").strip()
            item_wallets = [
                str(value).strip()
                for value in (item.get("frozen_wallets") or [])
                if str(value).strip()
            ]
            if not campaign_id or not item_wallets:
                raise SetupError(
                    "Campagna copyability ACTIVE priva di campaign_id o frozen_wallets."
                )
            for wallet in item_wallets:
                previous = wallet_owners.get(wallet)
                if previous is not None and previous != campaign_id:
                    raise SetupError(
                        "Wallet duplicato tra campagne copyability ACTIVE; "
                        "configurazione webhook rifiutata."
                    )
                wallet_owners[wallet] = campaign_id
            campaigns.append(item)

        if not campaigns:
            raise SetupError("Nessuna campagna copyability ACTIVE valida.")

        primary = next(
            (
                item
                for item in campaigns
                if item.get("campaign_role") in (None, "PRIMARY_FORWARD")
            ),
            None,
        )
        # M63 may intentionally pause the historical primary campaign and keep
        # one qualified candidate as the only ACTIVE campaign. In that case the
        # candidate is the reference campaign for registration and verification.
        reference_campaign = primary or campaigns[0]

        wallets = sorted(wallet_owners)
        if expected_exclusive_wallet and wallets != [expected_exclusive_wallet]:
            raise SetupError(
                "La configurazione M63 richiede esattamente il wallet esclusivo atteso."
            )
        campaign_ids = [str(item["campaign_id"]).strip() for item in campaigns]

        existing_raw = request_json(
            client,
            "GET",
            HELIUS_WEBHOOK_API,
            params={"api-key": helius_key},
        )
        existing = existing_raw if isinstance(existing_raw, list) else []
        exact = next(
            (
                item
                for item in existing
                if isinstance(item, dict)
                and str(item.get("webhookURL") or "").rstrip("/") == target_url.rstrip("/")
            ),
            None,
        )
        # Only an exact Gen4 endpoint may be updated automatically. A webhook
        # that happens to watch the same wallets may belong to another workflow.
        selected = exact
        safe_existing = [
            {
                "webhook_id": webhook_id(item),
                "webhook_url": item.get("webhookURL"),
                "address_count": len(item.get("accountAddresses") or []),
                "active": item.get("active"),
            }
            for item in existing
            if isinstance(item, dict)
        ]

        body = {
            "webhookURL": target_url,
            "accountAddresses": wallets,
            "webhookType": "raw",
            "authHeader": webhook_secret,
            "encoding": "jsonParsed",
            "txnStatus": "success",
        }

        selected_id = webhook_id(selected) if isinstance(selected, dict) else ""
        if selected_id:
            selected_detail = request_json(
                client,
                "GET",
                f"{HELIUS_WEBHOOK_API}/{selected_id}",
                params={"api-key": helius_key},
            )
            if not isinstance(selected_detail, dict):
                raise SetupError("Webhook Gen4 esistente non leggibile per ID.")
            if str(selected_detail.get("webhookURL") or "").rstrip("/") != target_url.rstrip("/"):
                raise SetupError("Webhook Gen4 per ID punta a un URL inatteso.")
            if str(selected_detail.get("webhookType") or "").lower() != "raw":
                raise SetupError("Webhook Gen4 per ID non è RAW.")
            configured = request_json(
                client,
                "PUT",
                f"{HELIUS_WEBHOOK_API}/{selected_id}",
                params={"api-key": helius_key},
                headers={"Content-Type": "application/json"},
                payload=body,
            )
        else:
            try:
                # Preserve unrelated webhooks whenever the provider plan has a
                # free slot. Replacement is a last-resort explicit operation.
                configured = request_json(
                    client,
                    "POST",
                    HELIUS_WEBHOOK_API,
                    params={"api-key": helius_key},
                    headers={"Content-Type": "application/json"},
                    payload=body,
                )
            except SetupError as create_error:
                if not existing or replace_confirmation != REPLACE_CONFIRMATION:
                    print(
                        "EXISTING_HELIUS_WEBHOOKS="
                        + json.dumps(safe_existing, ensure_ascii=False)
                    )
                    raise SetupError(
                        "Helius non ha consentito la creazione del webhook Gen4. "
                        "Nessun webhook esistente è stato modificato. Se il limite "
                        "del piano è stato raggiunto, rilancia con "
                        f"GEN4_REPLACE_WEBHOOK_CONFIRMATION={REPLACE_CONFIRMATION} "
                        "solo dopo aver verificato il webhook da sostituire. "
                        f"Dettaglio provider: {create_error}"
                    ) from create_error
                selected_id = webhook_id(existing[0])
                if not selected_id:
                    raise SetupError(
                        "Webhook esistente privo di identificatore; sostituzione rifiutata."
                    ) from create_error
                configured = request_json(
                    client,
                    "PUT",
                    f"{HELIUS_WEBHOOK_API}/{selected_id}",
                    params={"api-key": helius_key},
                    headers={"Content-Type": "application/json"},
                    payload=body,
                )

        configured_id = webhook_id(configured if isinstance(configured, dict) else {})
        if not configured_id:
            raise SetupError("Helius non ha restituito webhookID.")

        request_json(
            client,
            "PATCH",
            f"{HELIUS_WEBHOOK_API}/{configured_id}",
            params={"api-key": helius_key},
            headers={"Content-Type": "application/json"},
            payload={"active": True},
        )

        registered_campaigns: list[dict[str, Any]] = []
        for campaign_id in campaign_ids:
            registered = backend_request(
                client,
                "POST",
                backend_url,
                "/integrity/parser-gen4-copyability/webhook/configure",
                automation_key,
                {
                    "campaign_id": campaign_id,
                    "confirmation": CONFIGURE_CONFIRMATION,
                    "webhook_id": configured_id,
                    "webhook_url": target_url,
                    "active": True,
                },
            )
            if not isinstance(registered, dict):
                raise SetupError(
                    "Backend non ha confermato la registrazione webhook per una campagna."
                )
            registered_campaigns.append(registered)

        verified = request_json(
            client,
            "GET",
            f"{HELIUS_WEBHOOK_API}/{configured_id}",
            params={"api-key": helius_key},
        )
        if not bool((verified or {}).get("active")):
            raise SetupError("Webhook Helius creato ma non attivo.")
        if str((verified or {}).get("webhookURL") or "").rstrip("/") != target_url.rstrip("/"):
            raise SetupError("Webhook Helius attivo su un URL inatteso.")
        if set((verified or {}).get("accountAddresses") or []) != set(wallets):
            raise SetupError("Webhook Helius non monitora esattamente i wallet congelati.")

        print("GEN4_HELIUS_WEBHOOK=CONFIGURED")
        print(f"WEBHOOK_ID={configured_id}")
        print(f"WEBHOOK_URL={target_url}")
        print(f"WALLET_COUNT={len(wallets)}")
        print(f"ACTIVE_CAMPAIGN_COUNT={len(campaign_ids)}")
        print("COPYABILITY_CAMPAIGN_IDS=" + ",".join(campaign_ids))
        primary_registered = next(
            (
                item
                for item in registered_campaigns
                if str(item.get("campaign_id") or "").strip()
                == str(reference_campaign.get("campaign_id") or "").strip()
            ),
            registered_campaigns[0],
        )
        print(f"COPYABILITY_ANCHOR_AT={primary_registered.get('anchor_at')}")
        print("M61_SINGLE_WEBHOOK_UNION_ROUTING=ENABLED")
        print(
            "M63_EXCLUSIVE_CANDIDATE_WEBHOOK="
            + ("YES" if primary is None and len(campaign_ids) == 1 else "NO")
        )
        print("WEBHOOK_TYPE=raw")
        print("TXN_STATUS=success")
        print("AUTH_HEADER=CONFIGURED_REDACTED")


if __name__ == "__main__":
    try:
        main()
    except SetupError as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        raise SystemExit(1)
