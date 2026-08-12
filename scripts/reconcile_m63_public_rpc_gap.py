from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select

from backend.app.database.session import SessionLocal
from backend.app.models.gen4_copyability import (
    CanonicalParserGen4CopyabilityCampaign,
)
from backend.app.services.blockchain_parser_gen4_copyability_service import (
    record_gen4_copyability_raw_recovery_events,
)
from backend.app.services.m63_helius_credit_containment_service import (
    M63_CONTAINMENT_METADATA_KEY,
    M63_TARGET_WALLET,
)


APPLY_CONFIRMATION = "APPLY_M63_PUBLIC_RPC_GAP_RECOVERY"
DEFAULT_PUBLIC_RPC_URL = "https://api.mainnet-beta.solana.com"


class RecoveryError(RuntimeError):
    pass


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class PublicSolanaRpc:
    def __init__(self, url: str) -> None:
        parsed = urlsplit(url)
        hostname = str(parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not hostname:
            raise RecoveryError("URL RPC pubblico non valido.")
        if "helius" in hostname:
            raise RecoveryError("Il recupero M63 rifiuta endpoint Helius.")
        if parsed.username or parsed.password:
            raise RecoveryError("L'URL RPC non deve contenere credenziali.")
        self.url = url
        self.client = httpx.Client(timeout=45.0)
        self.requests = 0

    def close(self) -> None:
        self.client.close()

    def call(self, method: str, params: list[Any]) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, 4):
            self.requests += 1
            try:
                response = self.client.post(
                    self.url,
                    json={
                        "jsonrpc": "2.0",
                        "id": self.requests,
                        "method": method,
                        "params": params,
                    },
                )
                if response.status_code == 429 and attempt < 3:
                    time.sleep(float(attempt))
                    continue
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    raise RecoveryError("Risposta JSON-RPC inattesa.")
                if body.get("error"):
                    raise RecoveryError(
                        f"RPC {method} fallita; code="
                        f"{(body.get('error') or {}).get('code')}"
                    )
                return body.get("result")
            except (httpx.HTTPError, ValueError, RecoveryError) as error:
                last_error = error
                if attempt < 3:
                    time.sleep(float(attempt))
                    continue
        raise RecoveryError(
            f"RPC pubblico non disponibile per {method}: "
            f"{type(last_error).__name__}"
        ) from None


def _collect_signatures(
    rpc: PublicSolanaRpc,
    *,
    wallet_address: str,
    after: datetime,
    after_signature: str | None,
    maximum: int,
) -> tuple[list[dict[str, Any]], bool]:
    boundary = int(_aware(after).timestamp())
    collected: list[dict[str, Any]] = []
    before: str | None = None
    reached_boundary = False
    history_exhausted = False
    while len(collected) < maximum and not reached_boundary:
        config: dict[str, Any] = {
            "commitment": "finalized",
            "limit": min(1000, maximum - len(collected)),
        }
        if before:
            config["before"] = before
        if after_signature:
            config["until"] = after_signature
        page = rpc.call("getSignaturesForAddress", [wallet_address, config])
        if not isinstance(page, list) or not page:
            history_exhausted = True
            break
        for item in page:
            if not isinstance(item, dict):
                continue
            block_time = item.get("blockTime")
            if block_time is not None and int(block_time) <= boundary:
                reached_boundary = True
                break
            if item.get("err") is None and item.get("signature"):
                collected.append(item)
                if len(collected) >= maximum:
                    break
        before = str((page[-1] or {}).get("signature") or "")
        if not before or len(page) < int(config["limit"]):
            history_exhausted = True
            break
    return collected, reached_boundary or history_exhausted


def _fetch_transactions(
    rpc: PublicSolanaRpc,
    signatures: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    transactions: list[dict[str, Any]] = []
    unavailable = 0
    for item in reversed(signatures):
        signature = str(item.get("signature") or "")
        transaction = rpc.call(
            "getTransaction",
            [
                signature,
                {
                    "commitment": "finalized",
                    "encoding": "jsonParsed",
                    "maxSupportedTransactionVersion": 0,
                },
            ],
        )
        if not isinstance(transaction, dict):
            unavailable += 1
            continue
        transactions.append(transaction)
    return transactions, unavailable


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Riconcilia il gap M63 tramite RPC Solana pubblico, mai Helius."
    )
    parser.add_argument("--target-wallet", default=M63_TARGET_WALLET)
    parser.add_argument(
        "--rpc-url",
        default=os.getenv("SOLANA_PUBLIC_RECOVERY_RPC_URL", DEFAULT_PUBLIC_RPC_URL),
    )
    parser.add_argument("--max-signatures", type=int, default=1000)
    parser.add_argument("--confirmation", default="")
    return parser


def main() -> int:
    args = _parser().parse_args()
    maximum = max(1, min(int(args.max_signatures), 5000))
    apply = args.confirmation == APPLY_CONFIRMATION
    if args.confirmation and not apply:
        raise RecoveryError(f"Conferma richiesta: {APPLY_CONFIRMATION}")
    with SessionLocal() as db:
        campaigns = list(
            db.scalars(
                select(CanonicalParserGen4CopyabilityCampaign).where(
                    CanonicalParserGen4CopyabilityCampaign.status == "ACTIVE"
                )
            )
        )
        matching = [
            campaign
            for campaign in campaigns
            if args.target_wallet in (campaign.frozen_wallets or [])
        ]
        if len(matching) != 1:
            raise RecoveryError(
                "Serve esattamente una campagna ACTIVE per il wallet target."
            )
        campaign = matching[0]
        raw_containment = (campaign.technical_metadata or {}).get(
            M63_CONTAINMENT_METADATA_KEY
        )
        containment = (
            dict(raw_containment) if isinstance(raw_containment, dict) else {}
        )
        frozen_boundary = containment.get("public_rpc_recovery_after_utc")
        frozen_boundary_signature = str(
            containment.get("public_rpc_recovery_after_signature") or ""
        ).strip()
        try:
            boundary = (
                _aware(datetime.fromisoformat(str(frozen_boundary)))
                if frozen_boundary
                else (
                    _aware(campaign.last_webhook_at)
                    if campaign.last_webhook_at is not None
                    else None
                )
            )
        except (TypeError, ValueError):
            boundary = None
        if boundary is None:
            raise RecoveryError(
                "Confine webhook del gap assente o non valido."
            )
        closed_before = int(campaign.closed_trade_count or 0)

        rpc = PublicSolanaRpc(args.rpc_url)
        try:
            signatures, gap_boundary_reached = _collect_signatures(
                rpc,
                wallet_address=args.target_wallet,
                after=boundary,
                after_signature=frozen_boundary_signature or None,
                maximum=maximum,
            )
            if not gap_boundary_reached:
                raise RecoveryError(
                    "Limite firme raggiunto prima del confine del gap; "
                    "aumentare --max-signatures e ripetere senza applicare."
                )
            transactions, unavailable = _fetch_transactions(rpc, signatures)
        finally:
            rpc.close()

        if apply and unavailable:
            raise RecoveryError(
                "Una o più transazioni del gap non sono disponibili dal provider "
                "RPC pubblico; recupero rifiutato per sicurezza."
            )

        result = record_gen4_copyability_raw_recovery_events(
            db,
            wallet_address=args.target_wallet,
            transactions=transactions,
        )
        closed_after = int(campaign.closed_trade_count or 0)
        if closed_after != closed_before:
            db.rollback()
            raise RecoveryError(
                "Il recupero ha alterato i closed trade real-time; operazione annullata."
            )

        if apply:
            metadata = dict(campaign.technical_metadata or {})
            containment = dict(
                metadata.get(M63_CONTAINMENT_METADATA_KEY) or {}
            )
            containment["public_rpc_recovery_completed_at"] = datetime.now(
                timezone.utc
            ).isoformat()
            containment["public_rpc_recovery_signature_count"] = len(signatures)
            containment["public_rpc_recovery_counts_as_realtime_proof"] = False
            metadata[M63_CONTAINMENT_METADATA_KEY] = containment
            campaign.technical_metadata = metadata
            db.commit()
        else:
            db.rollback()

        print("=== M63 PUBLIC RPC GAP RECOVERY ===")
        print("MODE=" + ("APPLY" if apply else "DRY_RUN"))
        print(f"TARGET_CAMPAIGN_ID={campaign.campaign_id}")
        print(f"GAP_AFTER_UTC={boundary.isoformat()}")
        print(
            "GAP_AFTER_SIGNATURE="
            + ("FROZEN_PRESENT" if frozen_boundary_signature else "NOT_AVAILABLE")
        )
        print(f"SIGNATURES_FOUND={len(signatures)}")
        print("GAP_BOUNDARY_REACHED=YES")
        print(f"TRANSACTIONS_FETCHED={len(transactions)}")
        print(f"TRANSACTIONS_UNAVAILABLE={unavailable}")
        print("RECOVERY=" + json.dumps(result, sort_keys=True))
        print(f"CLOSED_REALTIME_TRADES_PRESERVED={closed_before}")
        print(f"PUBLIC_RPC_REQUESTS={rpc.requests}")
        print("HELIUS_REQUESTS=0")
        print("RECOVERY_COUNTS_AS_REALTIME_PROOF=NO")
        if not apply:
            print(f"CONFIRMATION_REQUIRED={APPLY_CONFIRMATION}")
            print("DATABASE_WRITES=0")
        else:
            print("RECOVERY=PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RecoveryError as error:
        print(f"RECOVERY=FAILED type={type(error).__name__}")
        raise SystemExit(1) from None
