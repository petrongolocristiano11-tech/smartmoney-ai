from __future__ import annotations

import base64
import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.constants import SOL_MINT
from backend.app.models.gen4_copyability import (
    CanonicalParserGen4CopyabilityCampaign,
    CanonicalParserGen4CopyabilityPosition,
    CanonicalParserGen4FastpathShadowEvent,
    CanonicalParserGen4WebhookReceipt,
)
from backend.app.services.blockchain_parser_gen4_copyability_service import (
    SOURCE_WEBHOOK,
    CanonicalParserGen4CopyabilityError,
    _entry_deterioration_bps,
    _quote,
    parse_raw_copyability_signal,
)
from backend.app.services.jupiter_swap_client import JupiterSwapClient
from backend.app.services.live_trading_errors import JupiterSwapError

FASTPATH_VERSION = "canonical-parser-gen4-processed-wss-fastpath-shadow/1"
FASTPATH_COMMITMENT = "processed"
FASTPATH_CANDIDATE_SCOPE = "M117E_CANDIDATE_WATCHLIST"
FASTPATH_CANDIDATE_POLICY_VERSION = "m117e-fastpath-candidate-entry-copyability/1"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = (len(ordered) - 1) * max(0.0, min(1.0, q))
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return float(ordered[lo])
    frac = pos - lo
    return float(ordered[lo] + (ordered[hi] - ordered[lo]) * frac)


def configured_fastpath_candidate_wallets() -> list[str]:
    if not bool(
        getattr(
            settings,
            "CANONICAL_PARSER_GEN4_FASTPATH_CANDIDATE_WATCHLIST_ENABLED",
            False,
        )
    ):
        return []
    raw = str(
        getattr(settings, "CANONICAL_PARSER_GEN4_FASTPATH_CANDIDATE_WALLETS", "")
        or ""
    )
    wallets = sorted(
        {item.strip() for item in re.split(r"[\s,;]+", raw.strip()) if item.strip()}
    )
    maximum = int(
        getattr(
            settings,
            "CANONICAL_PARSER_GEN4_FASTPATH_CANDIDATE_MAX_WALLETS",
            5,
        )
    )
    return wallets[: max(0, maximum)]


def _candidate_policy_snapshot() -> dict[str, Any]:
    # M117E is deliberately never more permissive than the operational M75
    # entry-copyability limits, even if generic M58-M60 env values are looser.
    return {
        "campaign_id": None,
        "policy_source": FASTPATH_CANDIDATE_POLICY_VERSION,
        "max_signal_age_ms": int(
            getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_MAX_SIGNAL_AGE_MS", 20_000)
        ),
        "max_quote_latency_ms": min(
            5_000,
            int(
                getattr(
                    settings,
                    "CANONICAL_PARSER_GEN4_COPYABILITY_MAX_QUOTE_LATENCY_MS",
                    5_000,
                )
            ),
        ),
        "max_price_impact_bps": min(
            500,
            int(
                getattr(
                    settings,
                    "CANONICAL_PARSER_GEN4_COPYABILITY_MAX_PRICE_IMPACT_BPS",
                    500,
                )
            ),
        ),
        "max_price_deterioration_bps": min(
            1_000,
            int(
                getattr(
                    settings,
                    "CANONICAL_PARSER_GEN4_COPYABILITY_MAX_PRICE_DETERIORATION_BPS",
                    1_000,
                )
            ),
        ),
        "simulated_input_lamports": int(
            getattr(
                settings,
                "CANONICAL_PARSER_GEN4_COPYABILITY_SIMULATED_INPUT_LAMPORTS",
                10_000_000,
            )
        ),
        "slippage_bps": int(
            getattr(settings, "CANONICAL_PARSER_GEN4_COPYABILITY_SLIPPAGE_BPS", 300)
        ),
        "commitment": FASTPATH_COMMITMENT,
        "m75_entry_caps_enforced": True,
        "live_execution": False,
        "paper_execution": False,
        "signer_access": False,
    }


def _is_candidate_event(event: CanonicalParserGen4FastpathShadowEvent) -> bool:
    return str(dict(event.evidence or {}).get("observation_scope") or "") == FASTPATH_CANDIDATE_SCOPE


def active_fastpath_wallets(db: Session) -> list[str]:
    campaigns = list(
        db.scalars(
            select(CanonicalParserGen4CopyabilityCampaign).where(
                CanonicalParserGen4CopyabilityCampaign.status == "ACTIVE"
            )
        )
    )
    return sorted(
        {
            str(wallet).strip()
            for campaign in campaigns
            for wallet in (campaign.frozen_wallets or [])
            if str(wallet).strip()
        }
    )


def _campaign_for_wallet(
    db: Session, wallet_address: str
) -> CanonicalParserGen4CopyabilityCampaign | None:
    campaigns = list(
        db.scalars(
            select(CanonicalParserGen4CopyabilityCampaign).where(
                CanonicalParserGen4CopyabilityCampaign.status == "ACTIVE"
            )
        )
    )
    for campaign in campaigns:
        if wallet_address in [str(x).strip() for x in (campaign.frozen_wallets or [])]:
            return campaign
    return None


def _decode_account_keys(encoded: str) -> list[str]:
    try:
        from solders.transaction import VersionedTransaction

        raw = base64.b64decode(encoded)
        tx = VersionedTransaction.from_bytes(raw)
        return [str(value) for value in tx.message.account_keys]
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"WSS_BASE64_TRANSACTION_DECODE_FAILED:{type(exc).__name__}") from exc


def normalize_helius_transaction_notification(message: dict[str, Any]) -> dict[str, Any]:
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    result = params.get("result") if isinstance(params.get("result"), dict) else {}
    signature = str(result.get("signature") or "").strip()
    if not signature:
        raise ValueError("WSS_SIGNATURE_MISSING")
    outer = result.get("transaction") if isinstance(result.get("transaction"), dict) else {}
    meta = outer.get("meta") if isinstance(outer.get("meta"), dict) else {}
    tx_value = outer.get("transaction")

    if isinstance(tx_value, dict):
        transaction = tx_value
        signatures = transaction.get("signatures")
        if not isinstance(signatures, list) or not signatures:
            transaction = dict(transaction)
            transaction["signatures"] = [signature]
    elif isinstance(tx_value, list) and tx_value and isinstance(tx_value[0], str):
        account_keys = _decode_account_keys(tx_value[0])
        transaction = {
            "signatures": [signature],
            "message": {"accountKeys": account_keys},
        }
    else:
        raise ValueError("WSS_TRANSACTION_PAYLOAD_UNSUPPORTED")

    return {
        "signature": signature,
        "slot": result.get("slot"),
        "blockTime": None,
        "transaction": transaction,
        "meta": meta,
    }


def _policy_snapshot(campaign: CanonicalParserGen4CopyabilityCampaign) -> dict[str, Any]:
    return {
        "campaign_id": campaign.campaign_id,
        "max_signal_age_ms": int(campaign.max_signal_age_ms),
        "max_quote_latency_ms": int(campaign.max_quote_latency_ms),
        "max_price_impact_bps": int(campaign.max_price_impact_bps),
        "max_price_deterioration_bps": int(campaign.max_price_deterioration_bps),
        "simulated_input_lamports": int(campaign.simulated_input_lamports),
        "slippage_bps": int(campaign.slippage_bps),
        "commitment": FASTPATH_COMMITMENT,
        "live_execution": False,
        "paper_execution": False,
        "signer_access": False,
    }


def _policy_number(policy: Any, key: str, default: float) -> float:
    if isinstance(policy, dict):
        return float(policy.get(key, default))
    return float(getattr(policy, key, default))


def _provisional_rejection(
    policy: Any,
    *,
    quote_latency_ms: int,
    out_amount: int,
    transaction_built: bool,
    price_impact_bps: float,
    deterioration_bps: float | None,
) -> str | None:
    if quote_latency_ms > int(_policy_number(policy, "max_quote_latency_ms", 5_000)):
        return "QUOTE_TOO_SLOW"
    if out_amount <= 0:
        return "NO_EXECUTABLE_OUTPUT"
    if price_impact_bps > _policy_number(policy, "max_price_impact_bps", 500):
        return "PRICE_IMPACT_TOO_HIGH"
    if (
        deterioration_bps is not None
        and deterioration_bps
        > _policy_number(policy, "max_price_deterioration_bps", 1_000)
    ):
        return "PRICE_ALREADY_MOVED"
    if not transaction_built:
        return "UNSIGNED_TRANSACTION_NOT_BUILT"
    return None


def record_fastpath_notification(
    db: Session,
    *,
    message: dict[str, Any],
    jupiter_client: JupiterSwapClient,
    received_at: datetime | None = None,
) -> dict[str, Any]:
    observed = _aware(received_at) or _utc_now()
    payload = normalize_helius_transaction_notification(message)
    signature = str(payload["signature"])
    wallets = active_fastpath_wallets(db)
    if not wallets:
        return {"status": "IGNORED_NO_ACTIVE_WALLETS", "signature": signature}

    existing = db.scalar(
        select(CanonicalParserGen4FastpathShadowEvent).where(
            CanonicalParserGen4FastpathShadowEvent.signature == signature
        )
    )
    if existing is not None:
        existing.delivery_count = max(1, int(existing.delivery_count or 1)) + 1
        db.flush()
        return {"status": "DUPLICATE", "signature": signature}

    event = CanonicalParserGen4FastpathShadowEvent(
        event_id=str(uuid4()),
        signature=signature,
        slot=(int(payload["slot"]) if payload.get("slot") is not None else None),
        wallet_address="UNRESOLVED",
        matched_wallets=[],
        campaign_id=None,
        commitment=FASTPATH_COMMITMENT,
        fast_received_at=observed,
        fast_transaction_built=False,
        fast_provisional_copyable=False,
        policy_snapshot={},
        evidence={
            "version": FASTPATH_VERSION,
            "transaction_details": "full",
            "encoding": "jsonParsed",
            "token_accounts": "balanceChanged",
            "live_execution": False,
            "signer_access": False,
        },
        delivery_count=1,
    )

    try:
        signal = parse_raw_copyability_signal(payload, frozen_wallets=wallets)
        parsed_at = _utc_now()
        campaign = _campaign_for_wallet(db, signal.wallet_address)
        event.wallet_address = signal.wallet_address
        event.matched_wallets = [signal.wallet_address]
        event.side = signal.side
        event.token_mint = signal.token_mint
        event.token_decimals = signal.token_decimals
        event.wallet_effective_price_sol = signal.wallet_effective_price_sol
        event.fast_parse_completed_at = parsed_at
        event.fast_prequote_ms = max(
            0, int((parsed_at - observed).total_seconds() * 1000)
        )
        if campaign is None:
            event.parse_error_code = "FASTPATH_ACTIVE_CAMPAIGN_NOT_FOUND"
        else:
            event.campaign_id = campaign.campaign_id
            event.policy_snapshot = _policy_snapshot(campaign)
            if signal.side == "BUY":
                try:
                    quote = _quote(
                        input_mint=SOL_MINT,
                        output_mint=signal.token_mint,
                        amount_raw=int(campaign.simulated_input_lamports),
                        slippage_bps=int(campaign.slippage_bps),
                        client=jupiter_client,
                    )
                    deterioration = _entry_deterioration_bps(
                        signal,
                        quote.result,
                        slippage_bps=int(campaign.slippage_bps),
                    )
                    impact_bps = max(0.0, float(quote.result.price_impact_percent) * 100.0)
                    built = bool(quote.result.transaction)
                    reason = _provisional_rejection(
                        campaign,
                        quote_latency_ms=int(quote.latency_ms),
                        out_amount=int(quote.result.out_amount),
                        transaction_built=built,
                        price_impact_bps=impact_bps,
                        deterioration_bps=deterioration,
                    )
                    event.fast_quote_requested_at = quote.requested_at
                    event.fast_quote_received_at = quote.received_at
                    event.fast_quote_latency_ms = int(quote.latency_ms)
                    event.fast_price_deterioration_bps = deterioration
                    event.fast_price_impact_bps = impact_bps
                    event.fast_out_amount = int(quote.result.out_amount)
                    event.fast_transaction_built = built
                    event.fast_provisional_copyable = reason is None
                    event.fast_provisional_rejection_reason = reason
                except JupiterSwapError as exc:
                    event.quote_error_code = str(exc.code)
            else:
                event.fast_provisional_rejection_reason = "NOT_A_BUY_SIGNAL"
    except CanonicalParserGen4CopyabilityError as exc:
        event.parse_error_code = str(exc.code)
        event.evidence = {
            **event.evidence,
            "parser_evidence": dict(exc.evidence or {}),
        }
    except ValueError as exc:
        event.parse_error_code = str(exc)[:120]

    try:
        with db.begin_nested():
            db.add(event)
            db.flush()
    except IntegrityError:
        return {"status": "DUPLICATE_RACE", "signature": signature}
    return {
        "status": "RECORDED",
        "signature": signature,
        "wallet": event.wallet_address,
        "side": event.side,
        "provisional_copyable": bool(event.fast_provisional_copyable),
        "rejection": event.fast_provisional_rejection_reason,
    }


def record_fastpath_candidate_notification(
    db: Session,
    *,
    message: dict[str, Any],
    jupiter_client: JupiterSwapClient,
    received_at: datetime | None = None,
) -> dict[str, Any]:
    observed = _aware(received_at) or _utc_now()
    payload = normalize_helius_transaction_notification(message)
    signature = str(payload["signature"])
    wallets = configured_fastpath_candidate_wallets()
    if not wallets:
        return {"status": "IGNORED_NO_CANDIDATE_WALLETS", "signature": signature}

    event = CanonicalParserGen4FastpathShadowEvent(
        event_id=str(uuid4()),
        signature=signature,
        slot=(int(payload["slot"]) if payload.get("slot") is not None else None),
        wallet_address="UNRESOLVED",
        matched_wallets=[],
        campaign_id=None,
        commitment=FASTPATH_COMMITMENT,
        fast_received_at=observed,
        fast_transaction_built=False,
        fast_provisional_copyable=False,
        policy_snapshot=_candidate_policy_snapshot(),
        evidence={
            "version": FASTPATH_VERSION,
            "candidate_version": FASTPATH_CANDIDATE_POLICY_VERSION,
            "observation_scope": FASTPATH_CANDIDATE_SCOPE,
            "transaction_details": "full",
            "encoding": "jsonParsed",
            "token_accounts": "balanceChanged",
            "provisional_only": True,
            "mutates_copyability_campaigns": False,
            "live_execution": False,
            "signer_access": False,
        },
        delivery_count=1,
    )

    try:
        signal = parse_raw_copyability_signal(payload, frozen_wallets=wallets)
        parsed_at = _utc_now()
        event.wallet_address = signal.wallet_address
        event.matched_wallets = [signal.wallet_address]
        event.side = signal.side
        event.token_mint = signal.token_mint
        event.token_decimals = signal.token_decimals
        event.wallet_effective_price_sol = signal.wallet_effective_price_sol
        event.fast_parse_completed_at = parsed_at
        event.fast_prequote_ms = max(
            0, int((parsed_at - observed).total_seconds() * 1000)
        )
        if signal.side == "BUY":
            policy = dict(event.policy_snapshot or {})
            try:
                quote = _quote(
                    input_mint=SOL_MINT,
                    output_mint=signal.token_mint,
                    amount_raw=int(policy["simulated_input_lamports"]),
                    slippage_bps=int(policy["slippage_bps"]),
                    client=jupiter_client,
                )
                deterioration = _entry_deterioration_bps(
                    signal,
                    quote.result,
                    slippage_bps=int(policy["slippage_bps"]),
                )
                impact_bps = max(
                    0.0, float(quote.result.price_impact_percent) * 100.0
                )
                built = bool(quote.result.transaction)
                reason = _provisional_rejection(
                    policy,
                    quote_latency_ms=int(quote.latency_ms),
                    out_amount=int(quote.result.out_amount),
                    transaction_built=built,
                    price_impact_bps=impact_bps,
                    deterioration_bps=deterioration,
                )
                event.fast_quote_requested_at = quote.requested_at
                event.fast_quote_received_at = quote.received_at
                event.fast_quote_latency_ms = int(quote.latency_ms)
                event.fast_price_deterioration_bps = deterioration
                event.fast_price_impact_bps = impact_bps
                event.fast_out_amount = int(quote.result.out_amount)
                event.fast_transaction_built = built
                event.fast_provisional_copyable = reason is None
                event.fast_provisional_rejection_reason = reason
            except JupiterSwapError as exc:
                event.quote_error_code = str(exc.code)
        else:
            event.fast_provisional_rejection_reason = "NOT_A_BUY_SIGNAL"
    except CanonicalParserGen4CopyabilityError as exc:
        event.parse_error_code = str(exc.code)
        event.evidence = {
            **event.evidence,
            "parser_evidence": dict(exc.evidence or {}),
        }
    except ValueError as exc:
        event.parse_error_code = str(exc)[:120]

    # Candidate rows use the same dedicated M117D audit table but no campaign_id.
    # They can never create M114/M117 positions/counters because this service never
    # calls the copyability campaign worker.
    try:
        with db.begin_nested():
            db.add(event)
            db.flush()
    except IntegrityError:
        existing = db.scalar(
            select(CanonicalParserGen4FastpathShadowEvent).where(
                CanonicalParserGen4FastpathShadowEvent.signature == signature,
                CanonicalParserGen4FastpathShadowEvent.wallet_address
                == event.wallet_address,
            )
        )
        if existing is not None and _is_candidate_event(existing):
            existing.delivery_count = max(1, int(existing.delivery_count or 1)) + 1
            db.flush()
        return {"status": "DUPLICATE_CANDIDATE", "signature": signature}

    return {
        "status": "RECORDED_CANDIDATE",
        "signature": signature,
        "wallet": event.wallet_address,
        "side": event.side,
        "provisional_copyable": bool(event.fast_provisional_copyable),
        "rejection": event.fast_provisional_rejection_reason,
        "quote_error": event.quote_error_code,
    }


def _candidate_status(
    rows: list[CanonicalParserGen4FastpathShadowEvent],
    *,
    recent_limit: int,
) -> dict[str, Any]:
    buys = [row for row in rows if row.side == "BUY"]
    quoted = [row for row in buys if row.fast_quote_received_at is not None]
    built = [row for row in buys if bool(row.fast_transaction_built)]
    copyable = [row for row in buys if bool(row.fast_provisional_copyable)]
    quote_errors = [row for row in buys if row.quote_error_code]
    parse_errors = [row for row in rows if row.parse_error_code]
    rejections = Counter(
        str(row.fast_provisional_rejection_reason)
        for row in buys
        if row.fast_provisional_rejection_reason
    )
    rejection_total = max(0, len(buys) - len(copyable))
    quote_latencies = [
        float(row.fast_quote_latency_ms)
        for row in quoted
        if row.fast_quote_latency_ms is not None
    ]
    processing_to_quote = [
        float((row.fast_prequote_ms or 0) + (row.fast_quote_latency_ms or 0))
        for row in quoted
    ]
    deterioration = [
        float(row.fast_price_deterioration_bps)
        for row in quoted
        if row.fast_price_deterioration_bps is not None
    ]
    impact = [
        float(row.fast_price_impact_bps)
        for row in quoted
        if row.fast_price_impact_bps is not None
    ]
    evidence_sufficient = len(buys) >= 20
    reject_rate = 100.0 * rejection_total / len(buys) if buys else 100.0
    acceptance_rate = 100.0 * len(copyable) / len(buys) if buys else 0.0
    build_coverage = 100.0 * len(built) / len(buys) if buys else 0.0
    ordered = sorted(rows, key=lambda row: row.fast_received_at, reverse=True)
    configured = configured_fastpath_candidate_wallets()
    return {
        "version": FASTPATH_CANDIDATE_POLICY_VERSION,
        "enabled": bool(configured),
        "configured_wallets": configured,
        "observation_scope": FASTPATH_CANDIDATE_SCOPE,
        "provisional_only": True,
        "event_count": len(rows),
        "buy_count": len(buys),
        "quoted_buy_count": len(quoted),
        "built_buy_count": len(built),
        "provisional_copyable_count": len(copyable),
        "quote_error_count": len(quote_errors),
        "parse_error_count": len(parse_errors),
        "entry_acceptance_rate_percent": round(acceptance_rate, 8),
        "entry_reject_rate_percent": round(reject_rate, 8),
        "unsigned_build_coverage_percent_of_buys": round(build_coverage, 8),
        "rejection_breakdown": dict(sorted(rejections.items())),
        "quote_latency_ms": {
            "p50": _percentile(quote_latencies, 0.50),
            "p95": _percentile(quote_latencies, 0.95),
        },
        "fast_received_to_quote_ms": {
            "p50": _percentile(processing_to_quote, 0.50),
            "p95": _percentile(processing_to_quote, 0.95),
        },
        "price_deterioration_bps": {
            "p50": _percentile(deterioration, 0.50),
            "p95": _percentile(deterioration, 0.95),
            "max": max(deterioration) if deterioration else None,
        },
        "price_impact_bps": {
            "p95": _percentile(impact, 0.95),
            "max": max(impact) if impact else None,
        },
        "entry_gate": {
            "minimum_attempts": 20,
            "attempts_met": evidence_sufficient,
            "maximum_reject_rate_percent": 20.0,
            "reject_rate_pass": bool(
                evidence_sufficient and reject_rate <= 20.0
            ),
            "price_already_moved_limit_bps": 1_000,
            "price_already_moved_unchanged": True,
        },
        "m75_forward_pass": False,
        "m75_forward_pass_reason": (
            "CANDIDATE_ENTRY_ONLY_NO_24H_CLOSED_WEBHOOK_PROOF"
        ),
        "recent": [
            {
                "signature": row.signature,
                "wallet": row.wallet_address,
                "side": row.side,
                "fast_received_at": row.fast_received_at,
                "fast_prequote_ms": row.fast_prequote_ms,
                "fast_quote_latency_ms": row.fast_quote_latency_ms,
                "fast_price_deterioration_bps": row.fast_price_deterioration_bps,
                "fast_price_impact_bps": row.fast_price_impact_bps,
                "fast_transaction_built": row.fast_transaction_built,
                "fast_provisional_copyable": row.fast_provisional_copyable,
                "fast_rejection": row.fast_provisional_rejection_reason,
                "parse_error": row.parse_error_code,
                "quote_error": row.quote_error_code,
            }
            for row in ordered[: max(1, min(int(recent_limit), 500))]
        ],
        "safety": {
            "campaign_created": False,
            "campaign_metrics_mutated": False,
            "positions_created": 0,
            "live_execution": False,
            "signer_access": False,
            "submitted_transactions": 0,
            "paper_orders": 0,
        },
    }


def _reconciled_rejection(event: CanonicalParserGen4FastpathShadowEvent) -> str | None:
    policy = dict(event.policy_snapshot or {})
    if event.side != "BUY":
        return "NOT_A_BUY_SIGNAL"
    if event.fast_quote_received_at is None or event.webhook_block_time is None:
        return "BLOCK_TIME_UNAVAILABLE"
    end_ms = max(
        0,
        int(
            (
                _aware(event.fast_quote_received_at) - _aware(event.webhook_block_time)
            ).total_seconds()
            * 1000
        ),
    )
    if end_ms > int(policy.get("max_signal_age_ms") or 20_000):
        return "SIGNAL_TOO_OLD"
    if (event.fast_quote_latency_ms or 0) > int(policy.get("max_quote_latency_ms") or 5_000):
        return "QUOTE_TOO_SLOW"
    if (event.fast_out_amount or 0) <= 0:
        return "NO_EXECUTABLE_OUTPUT"
    if (event.fast_price_impact_bps or 0.0) > float(policy.get("max_price_impact_bps") or 500):
        return "PRICE_IMPACT_TOO_HIGH"
    if (
        event.fast_price_deterioration_bps is not None
        and event.fast_price_deterioration_bps
        > float(policy.get("max_price_deterioration_bps") or 1_000)
    ):
        return "PRICE_ALREADY_MOVED"
    if not event.fast_transaction_built:
        return "UNSIGNED_TRANSACTION_NOT_BUILT"
    return None


def reconcile_fastpath_events(db: Session, *, limit: int = 200) -> dict[str, int]:
    rows = list(
        db.scalars(
            select(CanonicalParserGen4FastpathShadowEvent)
            .where(CanonicalParserGen4FastpathShadowEvent.webhook_reconciled_at.is_(None))
            .order_by(CanonicalParserGen4FastpathShadowEvent.fast_received_at)
            .limit(max(1, min(int(limit), 1000)))
        )
    )
    reconciled = 0
    for event in rows:
        if _is_candidate_event(event):
            continue
        receipt = db.scalar(
            select(CanonicalParserGen4WebhookReceipt)
            .where(
                CanonicalParserGen4WebhookReceipt.signature == event.signature,
                CanonicalParserGen4WebhookReceipt.source == SOURCE_WEBHOOK,
            )
            .order_by(CanonicalParserGen4WebhookReceipt.received_at.asc())
            .limit(1)
        )
        if receipt is None:
            continue
        event.webhook_received_at = _aware(receipt.received_at)
        event.webhook_block_time = _aware(receipt.block_time)
        event.webhook_reconciled_at = _utc_now()
        event.fast_lead_vs_webhook_ms = int(
            (
                _aware(receipt.received_at) - _aware(event.fast_received_at)
            ).total_seconds()
            * 1000
        )
        if event.fast_quote_received_at is not None and event.webhook_block_time is not None:
            event.fast_end_to_quote_ms = max(
                0,
                int(
                    (
                        _aware(event.fast_quote_received_at) - _aware(event.webhook_block_time)
                    ).total_seconds()
                    * 1000
                ),
            )
        position = db.scalar(
            select(CanonicalParserGen4CopyabilityPosition)
            .where(
                CanonicalParserGen4CopyabilityPosition.entry_signature == event.signature,
                CanonicalParserGen4CopyabilityPosition.wallet_address == event.wallet_address,
            )
            .order_by(CanonicalParserGen4CopyabilityPosition.id.asc())
            .limit(1)
        )
        if position is not None:
            event.confirmed_path_quote_received_at = _aware(position.entry_quote_received_at)
            event.confirmed_path_end_to_quote_ms = position.entry_end_to_quote_ms
        reason = _reconciled_rejection(event)
        event.fast_reconciled_rejection_reason = reason
        event.fast_reconciled_copyable = reason is None
        reconciled += 1
    db.flush()
    return {"scanned": len(rows), "reconciled": reconciled}


def get_gen4_fastpath_shadow_status(
    db: Session, *, recent_limit: int = 50
) -> dict[str, Any]:
    limit = max(1, min(int(recent_limit), 500))
    raw_all_rows = list(db.scalars(select(CanonicalParserGen4FastpathShadowEvent)))
    candidate_rows = [row for row in raw_all_rows if _is_candidate_event(row)]
    all_rows = [row for row in raw_all_rows if not _is_candidate_event(row)]
    rows = sorted(
        all_rows, key=lambda row: row.fast_received_at, reverse=True
    )[:limit]

    buys = [row for row in all_rows if row.side == "BUY"]
    quoted = [row for row in buys if row.fast_quote_received_at is not None]
    reconciled = [row for row in quoted if row.webhook_reconciled_at is not None]
    leads = [
        float(row.fast_lead_vs_webhook_ms)
        for row in reconciled
        if row.fast_lead_vs_webhook_ms is not None
    ]
    fast_end = [
        float(row.fast_end_to_quote_ms)
        for row in reconciled
        if row.fast_end_to_quote_ms is not None
    ]
    confirmed_end = [
        float(row.confirmed_path_end_to_quote_ms)
        for row in reconciled
        if row.confirmed_path_end_to_quote_ms is not None
    ]
    return {
        "version": FASTPATH_VERSION,
        "enabled": bool(
            getattr(settings, "CANONICAL_PARSER_GEN4_FASTPATH_SHADOW_ENABLED", False)
        ),
        "commitment": FASTPATH_COMMITMENT,
        "active_wallets": active_fastpath_wallets(db),
        # These top-level counters intentionally exclude M117E candidate rows so
        # the existing M117D evidence series remains comparable and uncontaminated.
        "event_count": len(all_rows),
        "buy_count": len(buys),
        "quoted_buy_count": len(quoted),
        "reconciled_buy_count": len(reconciled),
        "fast_provisional_copyable_count": sum(
            bool(row.fast_provisional_copyable) for row in buys
        ),
        "fast_reconciled_copyable_count": sum(
            row.fast_reconciled_copyable is True for row in buys
        ),
        "fast_lead_vs_webhook_ms": {
            "p50": _percentile(leads, 0.50),
            "p95": _percentile(leads, 0.95),
        },
        "fast_end_to_quote_ms": {
            "p50": _percentile(fast_end, 0.50),
            "p95": _percentile(fast_end, 0.95),
        },
        "confirmed_path_end_to_quote_ms": {
            "p50": _percentile(confirmed_end, 0.50),
            "p95": _percentile(confirmed_end, 0.95),
        },
        "recent": [
            {
                "signature": row.signature,
                "wallet": row.wallet_address,
                "side": row.side,
                "fast_received_at": row.fast_received_at,
                "fast_prequote_ms": row.fast_prequote_ms,
                "fast_quote_latency_ms": row.fast_quote_latency_ms,
                "fast_end_to_quote_ms": row.fast_end_to_quote_ms,
                "fast_lead_vs_webhook_ms": row.fast_lead_vs_webhook_ms,
                "confirmed_path_end_to_quote_ms": (
                    row.confirmed_path_end_to_quote_ms
                ),
                "fast_price_deterioration_bps": row.fast_price_deterioration_bps,
                "fast_provisional_copyable": row.fast_provisional_copyable,
                "fast_reconciled_copyable": row.fast_reconciled_copyable,
                "fast_rejection": row.fast_reconciled_rejection_reason
                or row.fast_provisional_rejection_reason,
                "parse_error": row.parse_error_code,
                "quote_error": row.quote_error_code,
            }
            for row in rows
        ],
        "candidate_watchlist": _candidate_status(
            candidate_rows, recent_limit=limit
        ),
        "safety": {
            "live_execution": False,
            "signer_access": False,
            "submitted_transactions": 0,
            "paper_orders": 0,
            "m114_m117_metrics_mutated": False,
            "m117d_official_counters_include_candidate_rows": False,
        },
    }
