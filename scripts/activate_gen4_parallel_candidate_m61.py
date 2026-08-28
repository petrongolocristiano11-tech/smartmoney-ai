from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any

import httpx


BACKEND_URL = os.environ.get(
    "GEN4_BACKEND_URL",
    "https://smartmoney-ai-production-0042.up.railway.app",
).rstrip("/")
STATUS_PATH = "/integrity/parser-gen4-copyability/status?recent_limit=5"
START_PATH = "/integrity/parser-gen4-copyability/start-qualified-candidate"
CONFIGURE_PATH = "/integrity/parser-gen4-copyability/webhook/configure"
STOP_PATH = "/integrity/parser-gen4-copyability/stop"
WEBHOOK_PATH = "/integrity/parser-gen4-copyability/webhook/helius"
HELIUS_WEBHOOK_API = "https://api-mainnet.helius-rpc.com/v0/webhooks"

EXPECTED_PRIMARY_CAMPAIGN_ID = "89026d62-1e4e-452b-b0bf-8a5e3dd373e4"
EXPECTED_PRIMARY_WALLETS = {
    "FsKYLBwxLQk5YMNSPYQcqceW6o8tJGF7U1aBHyEvGAyE",
    "2ZwYWRaQR7X3zcD7VX8u4Ke8znPQuKrVpRnU3Tp6UH7S",
}
CANDIDATE_WALLET = os.environ.get(
    "M61_CANDIDATE_WALLET",
    "Bs34SxJUSjUntbsWDEZrFKEcCdJfSuF9KiwtFdJ1Tfsd",
).strip()
START_CONFIRMATION = "START_GEN4_QUALIFIED_CANDIDATE_COPYABILITY"
CONFIGURE_CONFIRMATION = "CONFIGURE_GEN4_COPYABILITY_WEBHOOK"
STOP_CONFIRMATION = "STOP_GEN4_REALTIME_COPYABILITY"


class ActivationError(RuntimeError):
    pass


@dataclass
class ActivationState:
    candidate_id: str | None = None
    candidate_created_now: bool = False
    candidate_existed_before: bool = False
    candidate_was_monitored_before: bool | None = None
    webhook_id: str = ""
    primary_webhook_id: str = ""
    original_addresses: list[str] | None = None
    rollback_addresses: list[str] | None = None
    webhook_updated: bool = False
    repaired_empty_webhook: bool = False
    primary_anchor_before: str = ""
    primary_counts_before: dict[str, Any] | None = None


def require_env(name: str) -> str:
    value = str(os.environ.get(name) or "").strip()
    if not value:
        raise ActivationError(f"Variabile richiesta mancante: {name}")
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
        detail = body.get("detail") if isinstance(body, dict) else None
        raise ActivationError(
            f"Backend {method} {path} HTTP {response.status_code}: "
            f"{detail or 'risposta non valida'}"
        )
    if not isinstance(body, dict):
        raise ActivationError(f"Backend {method} {path}: risposta non-oggetto")
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
        message = None
        if isinstance(body, dict):
            message = body.get("error") or body.get("message")
        raise ActivationError(
            f"Helius {method} HTTP {response.status_code}: "
            f"{str(message or 'errore')[:240]}"
        )
    return body


def webhook_id(item: dict[str, Any]) -> str:
    return str(item.get("webhookID") or item.get("webhookId") or "").strip()


def desired_webhook_body(
    *,
    target_url: str,
    addresses: list[str],
    webhook_secret: str,
) -> dict[str, Any]:
    return {
        "webhookURL": target_url,
        "accountAddresses": sorted(set(addresses)),
        "webhookType": "raw",
        "authHeader": webhook_secret,
        "encoding": "jsonParsed",
        "txnStatus": "success",
    }


def selection_snapshot() -> dict[str, Any]:
    return {
        "activity_gate": "PASS",
        "buy_sell_parsing": "PASS",
        "quality_gate": "PASS",
        "observed_profitability": "PASS",
        "gen4_copyability": "PASS",
        "activity_window_days": 7,
        "swaps_7d": 74,
        "swaps_24h": 49,
        "buys_7d": 45,
        "sells_7d": 29,
        "active_days_7d": 4,
        "unknown_swap_ratio_percent": 0.0,
        "unique_tokens_7d": 9,
        "completed_token_pairs_7d": 9,
        "round_trip_token_ratio_percent": 100.0,
        "median_swap_sol": 1.213728,
        "dust_ratio_percent": 0.0,
        "top_token_concentration_percent": 27.03,
        "matched_sell_events": 27,
        "observed_win_rate_percent": 51.85,
        "observed_net_pnl_sol": 1.702192,
        "observed_profit_factor": 1.4252,
        "jupiter_copyability_pass": "6/6",
        "jupiter_input_sol": 0.01,
        "jupiter_slippage_bps": 300,
        "helius_selection_requests": 11,
        "selection_completed_at": "2026-08-07T20:45:00+00:00",
    }


def extract_campaigns(status: dict[str, Any]) -> list[dict[str, Any]]:
    campaigns = status.get("active_campaigns") or []
    if not isinstance(campaigns, list):
        raise ActivationError("Status M61 privo di active_campaigns valido")
    return [item for item in campaigns if isinstance(item, dict)]


def rollback_activation(
    client: httpx.Client,
    *,
    state: ActivationState,
    helius_key: str,
    automation_key: str,
    webhook_secret: str,
    target_url: str,
) -> None:
    errors: list[str] = []
    restore_addresses = (
        state.rollback_addresses
        if state.rollback_addresses is not None
        else state.original_addresses
    )
    if state.webhook_updated and state.webhook_id and restore_addresses is not None:
        try:
            helius_request(
                client,
                "PUT",
                f"{HELIUS_WEBHOOK_API}/{state.webhook_id}",
                helius_key,
                desired_webhook_body(
                    target_url=target_url,
                    addresses=restore_addresses,
                    webhook_secret=webhook_secret,
                ),
            )
            print("M61_FAILSAFE_WEBHOOK_RESTORED=YES", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"WEBHOOK_RESTORE:{type(exc).__name__}:{exc}")

    should_stop_candidate = (
        state.candidate_created_now
        or (
            state.candidate_existed_before
            and state.candidate_was_monitored_before is False
        )
    )
    if should_stop_candidate and state.candidate_id:
        try:
            backend_request(
                client,
                "POST",
                STOP_PATH,
                automation_key,
                {
                    "campaign_id": state.candidate_id,
                    "confirmation": STOP_CONFIRMATION,
                    "observed_at": None,
                },
            )
            print("M61_FAILSAFE_CANDIDATE_STOPPED=YES", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"CANDIDATE_STOP:{type(exc).__name__}:{exc}")

    if errors:
        print("M61_FAILSAFE_ERRORS=" + " | ".join(errors)[:1000], file=sys.stderr)


def activate(
    client: httpx.Client,
    *,
    state: ActivationState,
    helius_key: str,
    automation_key: str,
    webhook_secret: str,
    target_url: str,
) -> None:
    before = backend_request(client, "GET", STATUS_PATH, automation_key)
    if before.get("m61_parallel_candidate_support") is not True:
        raise ActivationError("Backend online non espone ancora il supporto M61")
    campaigns_before = extract_campaigns(before)
    primary = next(
        (
            item
            for item in campaigns_before
            if item.get("campaign_role") == "PRIMARY_FORWARD"
        ),
        None,
    )
    if primary is None:
        raise ActivationError("Campagna primaria M58-M60 non trovata")
    if str(primary.get("campaign_id")) != EXPECTED_PRIMARY_CAMPAIGN_ID:
        raise ActivationError("Campaign ID primario inatteso; attivazione fermata")
    if set(primary.get("frozen_wallets") or []) != EXPECTED_PRIMARY_WALLETS:
        raise ActivationError("I due wallet primari congelati non coincidono")
    state.primary_anchor_before = str(primary.get("anchor_at") or "")
    state.primary_counts_before = dict(primary.get("counts") or {})

    primary_webhook = primary.get("webhook") or {}
    if str(primary_webhook.get("status") or "") != "ACTIVE":
        raise ActivationError("Webhook primario non registrato ACTIVE nel database")
    state.primary_webhook_id = str(primary_webhook.get("webhook_id") or "").strip()
    primary_webhook_url = str(primary_webhook.get("url") or "").rstrip("/")
    if not state.primary_webhook_id:
        raise ActivationError("Webhook primario privo di ID nel database")
    if primary_webhook_url and primary_webhook_url != target_url.rstrip("/"):
        raise ActivationError("URL webhook primario nel database inatteso")

    # Validate the provider object BEFORE creating/restarting a candidate. This
    # prevents another archived candidate if the provider configuration itself
    # is not safe to repair.
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
        raise ActivationError("Webhook Gen4 esistente non trovato; M61 non ne crea uno nuovo")
    state.webhook_id = webhook_id(exact)
    if not state.webhook_id:
        raise ActivationError("Webhook Gen4 esistente privo di ID")
    if state.webhook_id != state.primary_webhook_id:
        raise ActivationError("Webhook Helius non coincide con il webhook primario registrato")

    exact_detail = helius_request(
        client,
        "GET",
        f"{HELIUS_WEBHOOK_API}/{state.webhook_id}",
        helius_key,
    )
    if not isinstance(exact_detail, dict):
        raise ActivationError("Webhook Gen4 esistente non leggibile per ID")
    if str(exact_detail.get("webhookURL") or "").rstrip("/") != target_url.rstrip("/"):
        raise ActivationError("Webhook Gen4 per ID punta a un URL inatteso")
    if str(exact_detail.get("webhookType") or "").lower() != "raw":
        raise ActivationError("Webhook Gen4 esistente non è RAW")
    if not bool(exact_detail.get("active")):
        raise ActivationError("Webhook Gen4 esistente non è attivo")

    state.original_addresses = [
        str(value).strip()
        for value in (exact_detail.get("accountAddresses") or [])
        if str(value).strip()
    ]
    original_set = set(state.original_addresses)
    union_set = EXPECTED_PRIMARY_WALLETS | {CANDIDATE_WALLET}
    allowed_existing = (
        set(),
        EXPECTED_PRIMARY_WALLETS,
        union_set,
    )
    if original_set not in allowed_existing:
        raise ActivationError("Webhook Gen4 monitora indirizzi inattesi")

    # Address membership is authoritative only from GET /webhooks/{id};
    # the provider list view may omit accountAddresses. If the detailed object
    # is genuinely empty, fail-safe rollback restores at least the primary set.
    state.repaired_empty_webhook = original_set == set()
    state.rollback_addresses = sorted(
        EXPECTED_PRIMARY_WALLETS if state.repaired_empty_webhook else original_set
    )
    state.candidate_was_monitored_before = CANDIDATE_WALLET in original_set

    existing_candidate = next(
        (
            item
            for item in campaigns_before
            if item.get("campaign_role") == "QUALIFIED_CANDIDATE"
            and set(item.get("frozen_wallets") or []) == {CANDIDATE_WALLET}
        ),
        None,
    )
    if existing_candidate is None:
        started = backend_request(
            client,
            "POST",
            START_PATH,
            automation_key,
            {
                "confirmation": START_CONFIRMATION,
                "candidate_wallets": [CANDIDATE_WALLET],
                "selection_snapshot": selection_snapshot(),
                "anchor_at": None,
                "actor_label": "M61_INSTALLER_REPAIR",
                "note": (
                    "Campagna candidata parallela riavviata dopo repair controllato "
                    "del webhook Helius e gate anti-burn del forward feed."
                ),
            },
        )
        state.candidate_id = str(started.get("campaign_id") or "").strip()
        state.candidate_created_now = not bool(started.get("idempotent_replay"))
    else:
        state.candidate_id = str(existing_candidate.get("campaign_id") or "").strip()
        state.candidate_existed_before = True

    if not state.candidate_id:
        raise ActivationError("Candidate campaign ID non restituito")

    union_wallets = sorted(union_set)
    if original_set != union_set:
        helius_request(
            client,
            "PUT",
            f"{HELIUS_WEBHOOK_API}/{state.webhook_id}",
            helius_key,
            desired_webhook_body(
                target_url=target_url,
                addresses=union_wallets,
                webhook_secret=webhook_secret,
            ),
        )
        state.webhook_updated = True

    # Primary DB metadata already points to this exact webhook and must not be
    # rewritten. Configure only the fresh candidate, preserving the original
    # primary anchor/configuration timestamp and counters.
    backend_request(
        client,
        "POST",
        CONFIGURE_PATH,
        automation_key,
        {
            "campaign_id": state.candidate_id,
            "confirmation": CONFIGURE_CONFIRMATION,
            "webhook_id": state.webhook_id,
            "webhook_url": target_url,
            "active": True,
            "observed_at": None,
        },
    )

    verified = helius_request(
        client,
        "GET",
        f"{HELIUS_WEBHOOK_API}/{state.webhook_id}",
        helius_key,
    )
    if not isinstance(verified, dict) or not bool(verified.get("active")):
        raise ActivationError("Webhook Helius M61 non attivo dopo l'update")
    if str(verified.get("webhookType") or "").lower() != "raw":
        raise ActivationError("Webhook Helius M61 non è RAW dopo l'update")
    if set(verified.get("accountAddresses") or []) != union_set:
        raise ActivationError("Webhook Helius M61 non monitora esattamente l'unione attesa")

    after = backend_request(client, "GET", STATUS_PATH, automation_key)
    campaigns_after = extract_campaigns(after)
    if int(after.get("active_campaign_count") or 0) != 2:
        raise ActivationError("Attese esattamente 2 campagne copyability attive")
    primary_after = next(
        item
        for item in campaigns_after
        if item.get("campaign_role") == "PRIMARY_FORWARD"
    )
    candidate_after = next(
        item for item in campaigns_after if item.get("campaign_id") == state.candidate_id
    )
    if str(primary_after.get("anchor_at") or "") != state.primary_anchor_before:
        raise ActivationError("Anchor della campagna primaria è cambiato")
    if set(primary_after.get("frozen_wallets") or []) != EXPECTED_PRIMARY_WALLETS:
        raise ActivationError("Wallet primari modificati")
    primary_webhook_after = primary_after.get("webhook") or {}
    if str(primary_webhook_after.get("webhook_id") or "") != state.primary_webhook_id:
        raise ActivationError("Webhook ID primario nel database è cambiato")
    primary_counts_after = dict(primary_after.get("counts") or {})
    for key, before_value in (state.primary_counts_before or {}).items():
        try:
            after_value = int(primary_counts_after.get(key) or 0)
            before_int = int(before_value or 0)
        except (TypeError, ValueError) as exc:
            raise ActivationError(
                f"Contatore primario non numerico: {key}"
            ) from exc
        if after_value < before_int:
            raise ActivationError(
                f"Contatore primario regredito durante l'attivazione: {key}"
            )
    if candidate_after.get("campaign_role") != "QUALIFIED_CANDIDATE":
        raise ActivationError("Ruolo della campagna candidata non valido")
    if set(candidate_after.get("frozen_wallets") or []) != {CANDIDATE_WALLET}:
        raise ActivationError("Wallet candidato congelato inatteso")
    if candidate_after.get("webhook", {}).get("status") != "ACTIVE":
        raise ActivationError("Webhook non registrato come ACTIVE sulla candidata")

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
            raise ActivationError(f"Guardia sicurezza non valida: {key}")


def main() -> int:
    helius_key = require_env("HELIUS_API_KEY")
    automation_key = require_env("AUTOMATION_API_KEY")
    webhook_secret = require_env("GEN4_WEBHOOK_SECRET")
    target_url = f"{BACKEND_URL}{WEBHOOK_PATH}"
    state = ActivationState()

    print("M61_PARALLEL_CANDIDATE_ACTIVATION=STARTED")
    print(f"CANDIDATE_WALLET={CANDIDATE_WALLET}")
    print("HELIUS_API_KEY=REDACTED")
    print("AUTOMATION_API_KEY=REDACTED")
    print("WEBHOOK_SECRET=REDACTED")
    print("PAPER=DISABLED")
    print("LIVE=DISABLED")

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        try:
            activate(
                client,
                state=state,
                helius_key=helius_key,
                automation_key=automation_key,
                webhook_secret=webhook_secret,
                target_url=target_url,
            )
        except Exception:
            rollback_activation(
                client,
                state=state,
                helius_key=helius_key,
                automation_key=automation_key,
                webhook_secret=webhook_secret,
                target_url=target_url,
            )
            raise

    print("M61_PARALLEL_CANDIDATE_ACTIVATION=PASS")
    print(f"PRIMARY_CAMPAIGN_ID={EXPECTED_PRIMARY_CAMPAIGN_ID}")
    print(f"PRIMARY_ANCHOR_PRESERVED={state.primary_anchor_before}")
    print(f"CANDIDATE_CAMPAIGN_ID={state.candidate_id}")
    print(
        "CANDIDATE_CREATED_NOW="
        + ("YES" if state.candidate_created_now else "NO_IDEMPOTENT")
    )
    print(f"WEBHOOK_ID={state.webhook_id}")
    print("M61_EMPTY_PRIMARY_WEBHOOK_REPAIRED=" + ("YES" if state.repaired_empty_webhook else "NO_NOT_NEEDED"))
    print("PRIMARY_DB_WEBHOOK_METADATA_REWRITTEN=NO")
    print("WEBHOOK_TYPE=raw")
    print("WEBHOOK_WALLET_COUNT=3")
    print("ACTIVE_COPYABILITY_CAMPAIGNS=2")
    print("PRIMARY_EVIDENCE_PRESERVED=YES")
    print("NO_SIGNER_NO_SIGNATURE_NO_SUBMISSION_NO_PAPER_NO_LIVE")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("M61_PARALLEL_CANDIDATE_ACTIVATION=FAIL", file=sys.stderr)
        print(f"ERROR_TYPE={type(exc).__name__}", file=sys.stderr)
        print(f"ERROR_MESSAGE={str(exc)[:500]}", file=sys.stderr)
        raise SystemExit(1)
