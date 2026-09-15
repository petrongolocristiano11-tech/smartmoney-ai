from __future__ import annotations

import base64
import math
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
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
    CanonicalParserGen4FastpathSelectivePosition,
    CanonicalParserGen4FastpathShadowEvent,
    CanonicalParserGen4PromotedSelectiveActivation,
    CanonicalParserGen4PromotedSelectivePosition,
    CanonicalParserGen4WebhookReceipt,
)
from backend.app.services.blockchain_parser_gen4_copyability_service import (
    SOURCE_WEBHOOK,
    CanonicalParserGen4CopyabilityError,
    _allocate_integer,
    _conservative_out_amount,
    _entry_deterioration_bps,
    _quote,
    parse_raw_copyability_signal,
)
from backend.app.services.gen4_fastpath_native_m75_evidence_service import (
    load_fastpath_native_m75_bridge,
)
from backend.app.services.gen4_promoted_selective_lifecycle_service import (
    PROMOTED_POSITION_CLOSED,
    PROMOTED_POSITION_OPEN,
    PROMOTED_POSITION_OPEN_PARTIAL,
    get_promoted_activation_for_event,
)
from backend.app.services.gen4_selective_challenger_lifecycle_bridge_design_service import (
    PROMOTED_SELECTIVE_SCOPE,
)
from backend.app.services.gen4_m316_copyable_alpha_diagnostics_service import (
    build_m316_candidate_alpha_diagnostics,
    m316_closed_trade_metrics,
)
from backend.app.services.jupiter_swap_client import JupiterSwapClient
from backend.app.services.live_trading_errors import JupiterSwapError
from backend.app.services.gen4_promoted_exit_recovery_service import (
    PROMOTED_EXIT_RECOVERY_BACKOFF_SECONDS,
    PROMOTED_EXIT_RECOVERY_MAX_AGE_SECONDS,
    PROMOTED_EXIT_RECOVERY_MAX_ATTEMPTS,
    PROMOTED_EXIT_RECOVERY_TICK_SECONDS,
    is_recoverable_promoted_exit_error,
    promoted_exit_error_snapshot,
    schedule_promoted_exit_recovery,
)
from backend.app.services.pump_bonding_curve_shadow import (
    quote_pump_buy_exact_sol_in_shadow,
)

FASTPATH_VERSION = "canonical-parser-gen4-processed-wss-fastpath-shadow/1"
FASTPATH_COMMITMENT = "processed"
FASTPATH_CANDIDATE_SCOPE = "M117E_CANDIDATE_WATCHLIST"
FASTPATH_CANDIDATE_POLICY_VERSION = "m117e-fastpath-candidate-entry-copyability/1"
FASTPATH_SELECTIVE_POSITION_VERSION = "m138-fastpath-selective-position-shadow/1"
FASTPATH_SELECTIVE_SCOPE = "OFFICIAL_FASTPATH_SELECTIVE"
FASTPATH_SELECTIVE_ENTRY_SOURCE = "PROCESSED_WSS_FASTPATH"
FASTPATH_SELECTIVE_POSITION_OPEN = "OPEN"
FASTPATH_SELECTIVE_POSITION_OPEN_PARTIAL = "OPEN_PARTIAL"
FASTPATH_SELECTIVE_POSITION_CLOSED = "CLOSED"
PROMOTED_SELECTIVE_POSITION_VERSION = "m307-promoted-candidate-fastpath-selective-position/1"
PROMOTED_SELECTIVE_ENTRY_SOURCE = "PROCESSED_WSS_PROMOTED_CANDIDATE"
FASTPATH_SELECTIVE_MIN_CLOSED = 10
FASTPATH_SELECTIVE_MIN_PROFIT_FACTOR = 1.30
FASTPATH_SELECTIVE_MAX_DRAWDOWN_PERCENT = 15.0


def _jupiter_error_snapshot(exc: JupiterSwapError) -> dict[str, Any]:
    payload = dict(getattr(exc, "payload", None) or {})
    response = payload.get("response")
    safe_response: dict[str, Any] = {}
    if isinstance(response, dict):
        for key in ("code", "message", "error", "errorMessage"):
            if key in response:
                safe_response[key] = response[key]

    raw_rate_headers = payload.get("rate_limit_headers")
    rate_headers: dict[str, str] = {}
    if isinstance(raw_rate_headers, dict):
        for key in (
            "x-ratelimit-current",
            "x-ratelimit-remaining",
            "x-ratelimit-reset",
            "retry-after",
        ):
            value = raw_rate_headers.get(key)
            if value not in (None, ""):
                rate_headers[key] = str(value)

    return {
        "code": str(getattr(exc, "code", "") or ""),
        "internal_status_code": int(
            getattr(exc, "status_code", 0) or 0
        ),
        "http_status": payload.get("http_status"),
        "attempts": payload.get("attempts"),
        "retryable": payload.get("retryable"),
        "rate_limit_headers": rate_headers,
        "response": safe_response,
    }


def _is_jupiter_no_route_liquidity_rejection(exc: JupiterSwapError) -> bool:
    if str(getattr(exc, "code", "") or "") != "JUPITER_HTTP_ERROR":
        return False
    payload = dict(getattr(exc, "payload", None) or {})
    try:
        http_status = int(payload.get("http_status"))
    except (TypeError, ValueError):
        return False
    if http_status != 400:
        return False
    response = payload.get("response")
    if not isinstance(response, dict):
        return False
    message = str(response.get("error") or "").strip().casefold()
    return message == "no routes found"


def _record_jupiter_entry_error(
    event: CanonicalParserGen4FastpathShadowEvent,
    exc: JupiterSwapError,
) -> None:
    snapshot = _jupiter_error_snapshot(exc)
    event.evidence = {
        **dict(event.evidence or {}),
        "jupiter_error": snapshot,
    }
    if _is_jupiter_no_route_liquidity_rejection(exc):
        event.quote_error_code = None
        event.fast_provisional_copyable = False
        event.fast_provisional_rejection_reason = "NO_EXECUTABLE_OUTPUT"
        event.evidence = {
            **dict(event.evidence or {}),
            "jupiter_entry_classification": {
                "version": "jupiter-entry-error-classification/1",
                "provider": "JUPITER",
                "http_status": 400,
                "provider_error": "No routes found",
                "classification": "LIQUIDITY_PROTECTIVE_REJECT",
                "mapped_rejection": "NO_EXECUTABLE_OUTPUT",
                "historical_reclassification": False,
            },
        }
        return
    event.quote_error_code = str(exc.code)


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


def _proof_active_fastpath_campaigns(
    db: Session,
) -> list[CanonicalParserGen4CopyabilityCampaign]:
    return list(
        db.scalars(
            select(CanonicalParserGen4CopyabilityCampaign).where(
                CanonicalParserGen4CopyabilityCampaign.status == "ACTIVE",
                CanonicalParserGen4CopyabilityCampaign.webhook_status == "ACTIVE",
                CanonicalParserGen4CopyabilityCampaign.webhook_id.is_not(None),
                CanonicalParserGen4CopyabilityCampaign.webhook_configured_at.is_not(None),
            )
        )
    )


def active_fastpath_wallets(db: Session) -> list[str]:
    campaigns = _proof_active_fastpath_campaigns(db)
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
    campaigns = _proof_active_fastpath_campaigns(db)
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
        "blockTime": (
            result.get("blockTime")
            if result.get("blockTime") is not None
            else outer.get("blockTime")
        ),
        "transaction": transaction,
        "meta": meta,
    }


def fastpath_notification_wallet_hint(
    message: dict[str, Any],
    wallets: list[str],
) -> str | None:
    """Best-effort wallet key used only to preserve per-wallet WSS processing order."""
    try:
        payload = normalize_helius_transaction_notification(message)
    except Exception:  # noqa: BLE001
        return None
    observed: set[str] = set()
    transaction = payload.get("transaction")
    if isinstance(transaction, dict):
        message_value = transaction.get("message")
        if isinstance(message_value, dict):
            for item in list(message_value.get("accountKeys") or []):
                if isinstance(item, dict):
                    value = str(item.get("pubkey") or "").strip()
                else:
                    value = str(item or "").strip()
                if value:
                    observed.add(value)
    meta = payload.get("meta")
    if isinstance(meta, dict):
        for key in ("preTokenBalances", "postTokenBalances"):
            for item in list(meta.get(key) or []):
                if isinstance(item, dict):
                    owner = str(item.get("owner") or "").strip()
                    if owner:
                        observed.add(owner)
    matches = [str(wallet) for wallet in wallets if str(wallet) in observed]
    return matches[0] if len(matches) == 1 else None


def _policy_snapshot(campaign: CanonicalParserGen4CopyabilityCampaign) -> dict[str, Any]:
    return {
        "campaign_id": campaign.campaign_id,
        "max_signal_age_ms": int(campaign.max_signal_age_ms),
        "max_quote_latency_ms": int(campaign.max_quote_latency_ms),
        "max_price_impact_bps": int(campaign.max_price_impact_bps),
        "max_price_deterioration_bps": int(campaign.max_price_deterioration_bps),
        "simulated_input_lamports": int(campaign.simulated_input_lamports),
        "slippage_bps": int(campaign.slippage_bps),
        "estimated_network_fee_lamports": int(campaign.estimated_network_fee_lamports),
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


def _selective_exit_rejection(
    policy: Any,
    *,
    quote_latency_ms: int,
    out_amount: int,
    transaction_built: bool,
    price_impact_bps: float,
) -> str | None:
    if quote_latency_ms > int(_policy_number(policy, "max_quote_latency_ms", 5_000)):
        return "EXIT_QUOTE_TOO_SLOW"
    if out_amount <= 0:
        return "EXIT_NO_EXECUTABLE_OUTPUT"
    if price_impact_bps > _policy_number(policy, "max_price_impact_bps", 500):
        return "EXIT_PRICE_IMPACT_TOO_HIGH"
    if not transaction_built:
        return "EXIT_UNSIGNED_TRANSACTION_NOT_BUILT"
    return None


def _new_selective_position(
    *,
    event: CanonicalParserGen4FastpathShadowEvent,
    signal: Any,
    campaign: CanonicalParserGen4CopyabilityCampaign,
    quote: Any,
    conservative_out: int,
    deterioration_bps: float | None,
    price_impact_bps: float,
) -> CanonicalParserGen4FastpathSelectivePosition:
    return CanonicalParserGen4FastpathSelectivePosition(
        position_id=str(uuid4()),
        scope=FASTPATH_SELECTIVE_SCOPE,
        campaign_id=str(campaign.campaign_id),
        entry_fast_event_id=str(event.event_id),
        status=FASTPATH_SELECTIVE_POSITION_OPEN,
        wallet_address=str(signal.wallet_address),
        token_mint=str(signal.token_mint),
        token_decimals=int(signal.token_decimals),
        entry_signature=str(signal.signature),
        entry_source=FASTPATH_SELECTIVE_ENTRY_SOURCE,
        entry_received_at=_aware(event.fast_received_at) or _utc_now(),
        opened_at=_aware(quote.received_at) or _utc_now(),
        closed_at=None,
        entry_quote_latency_ms=int(quote.latency_ms),
        entry_price_deterioration_bps=deterioration_bps,
        entry_price_impact_bps=float(price_impact_bps),
        entry_transaction_built=bool(quote.result.transaction),
        entry_input_lamports=int(quote.result.in_amount),
        entry_output_token_raw=int(conservative_out),
        remaining_token_raw=int(conservative_out),
        allocated_entry_fee_lamports=int(campaign.estimated_network_fee_lamports),
        realized_output_lamports=0,
        allocated_exit_fee_lamports=0,
        pnl_lamports=None,
        return_percent=None,
        last_exit_signature=None,
        exit_quote_latency_ms=None,
        exit_price_impact_bps=None,
        exit_transaction_built=False,
        exit_copyable=False,
        close_reason=None,
        entry_quote={
            **dict(quote.sanitized or {}),
            "expected_out_amount": int(quote.result.out_amount),
            "conservative_out_amount": int(conservative_out),
            "slippage_haircut_applied": True,
        },
        exit_quotes=[],
        evidence={
            "version": FASTPATH_SELECTIVE_POSITION_VERSION,
            "scope": FASTPATH_SELECTIVE_SCOPE,
            "strict_forward_only": True,
            "source_fast_event_id": str(event.event_id),
            "source_signature": str(signal.signature),
            "mutates_copyability_campaign_metrics": False,
            "uses_copyability_position_table": False,
            "live_execution": False,
            "paper_execution": False,
            "signer_access": False,
        },
    )


def _record_selective_exit_error(
    positions: list[CanonicalParserGen4FastpathSelectivePosition],
    *,
    signature: str,
    code: str,
    observed_at: datetime,
) -> None:
    for position in positions:
        evidence = dict(position.evidence or {})
        failures = list(evidence.get("exit_failures") or [])
        failures.append(
            {
                "signature": signature,
                "code": code,
                "observed_at": observed_at.isoformat(),
            }
        )
        evidence["exit_failures"] = failures[-100:]
        position.evidence = evidence


def _apply_selective_sell_shadow(
    db: Session,
    *,
    event: CanonicalParserGen4FastpathShadowEvent,
    signal: Any,
    campaign: CanonicalParserGen4CopyabilityCampaign,
    jupiter_client: JupiterSwapClient,
) -> dict[str, Any]:
    positions = list(
        db.scalars(
            select(CanonicalParserGen4FastpathSelectivePosition)
            .where(
                CanonicalParserGen4FastpathSelectivePosition.scope
                == FASTPATH_SELECTIVE_SCOPE,
                CanonicalParserGen4FastpathSelectivePosition.campaign_id
                == str(campaign.campaign_id),
                CanonicalParserGen4FastpathSelectivePosition.wallet_address
                == str(signal.wallet_address),
                CanonicalParserGen4FastpathSelectivePosition.token_mint
                == str(signal.token_mint),
                CanonicalParserGen4FastpathSelectivePosition.status.in_(
                    [
                        FASTPATH_SELECTIVE_POSITION_OPEN,
                        FASTPATH_SELECTIVE_POSITION_OPEN_PARTIAL,
                    ]
                ),
                CanonicalParserGen4FastpathSelectivePosition.remaining_token_raw > 0,
            )
            .order_by(
                CanonicalParserGen4FastpathSelectivePosition.opened_at,
                CanonicalParserGen4FastpathSelectivePosition.id,
            )
        )
    )
    base = {
        "version": FASTPATH_SELECTIVE_POSITION_VERSION,
        "scope": FASTPATH_SELECTIVE_SCOPE,
        "side": "SELL",
        "open_positions_found": len(positions),
        "quote_attempted": False,
        "exit_applied": False,
        "positions_closed": 0,
        "mutates_copyability_campaign_metrics": False,
        "live_execution": False,
        "paper_execution": False,
        "signer_access": False,
    }
    if not positions:
        return {**base, "reason": "NO_OPEN_SELECTIVE_POSITION"}

    fraction = signal.sell_fraction
    if fraction is None or fraction <= 0:
        return {**base, "reason": "SELL_FRACTION_UNAVAILABLE"}

    weights = [int(position.remaining_token_raw) for position in positions]
    total_remaining = sum(weights)
    amount_to_sell = min(
        total_remaining,
        max(1, int(total_remaining * float(fraction))),
    )
    try:
        quote = _quote(
            input_mint=str(signal.token_mint),
            output_mint=SOL_MINT,
            amount_raw=int(amount_to_sell),
            slippage_bps=int(campaign.slippage_bps),
            client=jupiter_client,
        )
    except JupiterSwapError as exc:
        code = str(exc.code)
        _record_selective_exit_error(
            positions,
            signature=str(signal.signature),
            code=code,
            observed_at=_utc_now(),
        )
        return {
            **base,
            "quote_attempted": True,
            "quote_error": code,
            "reason": "EXIT_QUOTE_ERROR",
        }

    conservative_out = _conservative_out_amount(
        quote.result, int(campaign.slippage_bps)
    )
    impact_bps = max(0.0, float(quote.result.price_impact_percent) * 100.0)
    rejection = _selective_exit_rejection(
        campaign,
        quote_latency_ms=int(quote.latency_ms),
        out_amount=int(quote.result.out_amount),
        transaction_built=bool(quote.result.transaction),
        price_impact_bps=impact_bps,
    )
    if rejection is not None:
        _record_selective_exit_error(
            positions,
            signature=str(signal.signature),
            code=rejection,
            observed_at=_aware(quote.received_at) or _utc_now(),
        )
        return {
            **base,
            "quote_attempted": True,
            "quote_built": bool(quote.result.transaction),
            "quote_latency_ms": int(quote.latency_ms),
            "price_impact_bps": impact_bps,
            "reason": rejection,
        }

    sold_allocations = _allocate_integer(int(amount_to_sell), weights)
    out_allocations = _allocate_integer(int(conservative_out), sold_allocations)
    fee_allocations = _allocate_integer(
        int(campaign.estimated_network_fee_lamports), sold_allocations
    )
    closed = 0
    affected = 0
    for position, sold_raw, out_lamports, fee_lamports in zip(
        positions, sold_allocations, out_allocations, fee_allocations
    ):
        if sold_raw <= 0:
            continue
        affected += 1
        position.remaining_token_raw = max(
            0, int(position.remaining_token_raw) - int(sold_raw)
        )
        position.realized_output_lamports += int(out_lamports)
        position.allocated_exit_fee_lamports += int(fee_lamports)
        position.last_exit_signature = str(signal.signature)
        position.exit_quote_latency_ms = int(quote.latency_ms)
        position.exit_price_impact_bps = float(impact_bps)
        position.exit_transaction_built = bool(quote.result.transaction)
        position.exit_copyable = True
        exit_quotes = list(position.exit_quotes or [])
        exit_quotes.append(
            {
                "signature": str(signal.signature),
                "sell_fraction": float(fraction),
                "sold_token_raw": int(sold_raw),
                "out_lamports": int(out_lamports),
                "allocated_fee_lamports": int(fee_lamports),
                "quote": {
                    **dict(quote.sanitized or {}),
                    "expected_out_amount": int(quote.result.out_amount),
                    "conservative_out_amount": int(conservative_out),
                    "slippage_haircut_applied": True,
                },
                "quote_requested_at": quote.requested_at.isoformat(),
                "quote_received_at": quote.received_at.isoformat(),
            }
        )
        position.exit_quotes = exit_quotes[-100:]
        dust_limit = max(1, int(position.entry_output_token_raw * 0.001))
        if position.remaining_token_raw <= dust_limit or float(fraction) >= 0.999:
            position.remaining_token_raw = 0
            position.status = FASTPATH_SELECTIVE_POSITION_CLOSED
            position.closed_at = _aware(quote.received_at) or _utc_now()
            position.close_reason = "MIRRORED_WALLET_EXIT"
            cost = int(position.entry_input_lamports) + int(
                position.allocated_entry_fee_lamports
            )
            proceeds = int(position.realized_output_lamports) - int(
                position.allocated_exit_fee_lamports
            )
            position.pnl_lamports = proceeds - cost
            position.return_percent = (
                position.pnl_lamports / cost * 100.0 if cost > 0 else None
            )
            closed += 1
        else:
            position.status = FASTPATH_SELECTIVE_POSITION_OPEN_PARTIAL

    return {
        **base,
        "quote_attempted": True,
        "quote_built": bool(quote.result.transaction),
        "quote_latency_ms": int(quote.latency_ms),
        "price_impact_bps": impact_bps,
        "sell_fraction": float(fraction),
        "positions_affected": affected,
        "positions_closed": closed,
        "exit_applied": True,
    }



def _promoted_policy_matches_candidate_event(
    event: CanonicalParserGen4FastpathShadowEvent,
    activation: CanonicalParserGen4PromotedSelectiveActivation,
) -> bool:
    event_policy = dict(event.policy_snapshot or {})
    frozen = dict(activation.policy_snapshot or {})
    integer_keys = (
        "simulated_input_lamports",
        "slippage_bps",
        "max_quote_latency_ms",
        "max_price_impact_bps",
        "max_price_deterioration_bps",
    )
    for key in integer_keys:
        try:
            if int(event_policy.get(key)) != int(frozen.get(key)):
                return False
        except (TypeError, ValueError):
            return False
    return (
        event_policy.get("live_execution") is False
        and event_policy.get("paper_execution") is False
        and frozen.get("live_execution") is False
        and frozen.get("paper_execution") is False
        and frozen.get("automatic_live_activation") is False
    )


def _new_promoted_selective_position(
    *,
    event: CanonicalParserGen4FastpathShadowEvent,
    signal: Any,
    activation: CanonicalParserGen4PromotedSelectiveActivation,
    quote: Any,
    conservative_out: int,
    deterioration_bps: float | None,
    price_impact_bps: float,
) -> CanonicalParserGen4PromotedSelectivePosition:
    policy = dict(activation.policy_snapshot or {})
    return CanonicalParserGen4PromotedSelectivePosition(
        position_id=str(uuid4()),
        scope=PROMOTED_SELECTIVE_SCOPE,
        activation_db_id=int(activation.id),
        activation_id=str(activation.activation_id),
        entry_fast_event_id=str(event.event_id),
        status=PROMOTED_POSITION_OPEN,
        wallet_address=str(signal.wallet_address),
        token_mint=str(signal.token_mint),
        token_decimals=int(signal.token_decimals),
        entry_signature=str(signal.signature),
        entry_source=PROMOTED_SELECTIVE_ENTRY_SOURCE,
        entry_received_at=_aware(event.fast_received_at) or _utc_now(),
        opened_at=_aware(quote.received_at) or _utc_now(),
        closed_at=None,
        entry_quote_latency_ms=int(quote.latency_ms),
        entry_price_deterioration_bps=deterioration_bps,
        entry_price_impact_bps=float(price_impact_bps),
        entry_transaction_built=bool(quote.result.transaction),
        entry_input_lamports=int(quote.result.in_amount),
        entry_output_token_raw=int(conservative_out),
        remaining_token_raw=int(conservative_out),
        allocated_entry_fee_lamports=int(
            policy.get("estimated_network_fee_lamports") or 0
        ),
        realized_output_lamports=0,
        allocated_exit_fee_lamports=0,
        pnl_lamports=None,
        return_percent=None,
        last_exit_signature=None,
        exit_quote_latency_ms=None,
        exit_price_impact_bps=None,
        exit_transaction_built=False,
        exit_copyable=False,
        close_reason=None,
        entry_quote={
            **dict(quote.sanitized or {}),
            "expected_out_amount": int(quote.result.out_amount),
            "conservative_out_amount": int(conservative_out),
            "slippage_haircut_applied": True,
        },
        exit_quotes=[],
        evidence={
            "version": PROMOTED_SELECTIVE_POSITION_VERSION,
            "scope": PROMOTED_SELECTIVE_SCOPE,
            "activation_id": str(activation.activation_id),
            "activation_anchor_utc": (
                _aware(activation.activation_anchor_at) or _utc_now()
            ).isoformat(),
            "strict_post_activation_only": True,
            "prepromotion_backfill": False,
            "source_candidate_fast_event_id": str(event.event_id),
            "source_signature": str(signal.signature),
            "candidate_observation_scope_unchanged": True,
            "mutates_copyability_campaign_metrics": False,
            "uses_official_selective_position_table": False,
            "live_execution": False,
            "paper_execution": False,
            "signer_access": False,
        },
    )


def _record_promoted_exit_error(
    positions: list[CanonicalParserGen4PromotedSelectivePosition],
    *,
    signature: str,
    code: str,
    observed_at: datetime,
    details: dict[str, Any] | None = None,
) -> None:
    for position in positions:
        evidence = dict(position.evidence or {})
        failures = list(evidence.get("exit_failures") or [])
        record: dict[str, Any] = {
            "signature": signature,
            "code": code,
            "observed_at": observed_at.isoformat(),
        }
        if details:
            record["details"] = dict(details)
        failures.append(record)
        evidence["exit_failures"] = failures[-100:]
        position.evidence = evidence


def _apply_promoted_selective_sell_shadow(
    db: Session,
    *,
    event: CanonicalParserGen4FastpathShadowEvent,
    signal: Any,
    activation: CanonicalParserGen4PromotedSelectiveActivation,
    jupiter_client: JupiterSwapClient,
) -> dict[str, Any]:
    positions = list(
        db.scalars(
            select(CanonicalParserGen4PromotedSelectivePosition)
            .where(
                CanonicalParserGen4PromotedSelectivePosition.scope
                == PROMOTED_SELECTIVE_SCOPE,
                CanonicalParserGen4PromotedSelectivePosition.activation_db_id
                == int(activation.id),
                CanonicalParserGen4PromotedSelectivePosition.wallet_address
                == str(signal.wallet_address),
                CanonicalParserGen4PromotedSelectivePosition.token_mint
                == str(signal.token_mint),
                CanonicalParserGen4PromotedSelectivePosition.status.in_(
                    [PROMOTED_POSITION_OPEN, PROMOTED_POSITION_OPEN_PARTIAL]
                ),
                CanonicalParserGen4PromotedSelectivePosition.remaining_token_raw > 0,
            )
            .order_by(
                CanonicalParserGen4PromotedSelectivePosition.opened_at,
                CanonicalParserGen4PromotedSelectivePosition.id,
            )
        )
    )
    base = {
        "version": PROMOTED_SELECTIVE_POSITION_VERSION,
        "scope": PROMOTED_SELECTIVE_SCOPE,
        "activation_id": str(activation.activation_id),
        "side": "SELL",
        "open_positions_found": len(positions),
        "quote_attempted": False,
        "exit_applied": False,
        "positions_closed": 0,
        "prepromotion_backfill": False,
        "mutates_copyability_campaign_metrics": False,
        "live_execution": False,
        "paper_execution": False,
        "signer_access": False,
    }
    if not positions:
        return {**base, "reason": "NO_OPEN_PROMOTED_SELECTIVE_POSITION"}

    fraction = signal.sell_fraction
    if fraction is None or fraction <= 0:
        return {**base, "reason": "SELL_FRACTION_UNAVAILABLE"}

    policy = dict(activation.policy_snapshot or {})
    weights = [int(position.remaining_token_raw) for position in positions]
    total_remaining = sum(weights)
    amount_to_sell = min(
        total_remaining,
        max(1, int(total_remaining * float(fraction))),
    )
    sold_allocations = _allocate_integer(int(amount_to_sell), weights)
    try:
        quote = _quote(
            input_mint=str(signal.token_mint),
            output_mint=SOL_MINT,
            amount_raw=int(amount_to_sell),
            slippage_bps=int(policy["slippage_bps"]),
            client=jupiter_client,
        )
    except JupiterSwapError as exc:
        code = str(exc.code)
        observed_at = _aware(event.fast_received_at) or _utc_now()
        error_details = promoted_exit_error_snapshot(exc)
        if is_recoverable_promoted_exit_error(exc):
            recovery = schedule_promoted_exit_recovery(
                positions,
                signature=str(signal.signature),
                sell_fraction=float(fraction),
                sold_allocations=sold_allocations,
                observed_at=observed_at,
                error=exc,
            )
            return {
                **base,
                "quote_attempted": True,
                "quote_error": code,
                "reason": "EXIT_RECOVERY_SCHEDULED",
                "autonomous_exit_recovery": recovery,
            }
        _record_promoted_exit_error(
            positions,
            signature=str(signal.signature),
            code=code,
            observed_at=observed_at,
            details=error_details,
        )
        return {
            **base,
            "quote_attempted": True,
            "quote_error": code,
            "quote_error_details": error_details,
            "reason": "EXIT_QUOTE_ERROR",
        }

    conservative_out = _conservative_out_amount(
        quote.result, int(policy["slippage_bps"])
    )
    impact_bps = max(0.0, float(quote.result.price_impact_percent) * 100.0)
    rejection = _selective_exit_rejection(
        policy,
        quote_latency_ms=int(quote.latency_ms),
        out_amount=int(quote.result.out_amount),
        transaction_built=bool(quote.result.transaction),
        price_impact_bps=impact_bps,
    )
    if rejection is not None:
        _record_promoted_exit_error(
            positions,
            signature=str(signal.signature),
            code=rejection,
            observed_at=_aware(quote.received_at) or _utc_now(),
        )
        return {
            **base,
            "quote_attempted": True,
            "quote_built": bool(quote.result.transaction),
            "quote_latency_ms": int(quote.latency_ms),
            "price_impact_bps": impact_bps,
            "reason": rejection,
        }

    out_allocations = _allocate_integer(int(conservative_out), sold_allocations)
    fee_allocations = _allocate_integer(
        int(policy.get("estimated_network_fee_lamports") or 0),
        sold_allocations,
    )
    closed = 0
    affected = 0
    for position, sold_raw, out_lamports, fee_lamports in zip(
        positions, sold_allocations, out_allocations, fee_allocations
    ):
        if sold_raw <= 0:
            continue
        affected += 1
        position.remaining_token_raw = max(
            0, int(position.remaining_token_raw) - int(sold_raw)
        )
        position.realized_output_lamports += int(out_lamports)
        position.allocated_exit_fee_lamports += int(fee_lamports)
        position.last_exit_signature = str(signal.signature)
        position.exit_quote_latency_ms = int(quote.latency_ms)
        position.exit_price_impact_bps = float(impact_bps)
        position.exit_transaction_built = bool(quote.result.transaction)
        position.exit_copyable = True
        exit_quotes = list(position.exit_quotes or [])
        exit_quotes.append(
            {
                "signature": str(signal.signature),
                "sell_fraction": float(fraction),
                "sold_token_raw": int(sold_raw),
                "out_lamports": int(out_lamports),
                "allocated_fee_lamports": int(fee_lamports),
                "quote": {
                    **dict(quote.sanitized or {}),
                    "expected_out_amount": int(quote.result.out_amount),
                    "conservative_out_amount": int(conservative_out),
                    "slippage_haircut_applied": True,
                },
                "quote_requested_at": quote.requested_at.isoformat(),
                "quote_received_at": quote.received_at.isoformat(),
            }
        )
        position.exit_quotes = exit_quotes[-100:]
        dust_limit = max(1, int(position.entry_output_token_raw * 0.001))
        if position.remaining_token_raw <= dust_limit or float(fraction) >= 0.999:
            position.remaining_token_raw = 0
            position.status = PROMOTED_POSITION_CLOSED
            position.closed_at = _aware(quote.received_at) or _utc_now()
            position.close_reason = "MIRRORED_WALLET_EXIT"
            cost = int(position.entry_input_lamports) + int(
                position.allocated_entry_fee_lamports
            )
            proceeds = int(position.realized_output_lamports) - int(
                position.allocated_exit_fee_lamports
            )
            position.pnl_lamports = proceeds - cost
            position.return_percent = (
                position.pnl_lamports / cost * 100.0 if cost > 0 else None
            )
            closed += 1
        else:
            position.status = PROMOTED_POSITION_OPEN_PARTIAL

    return {
        **base,
        "quote_attempted": True,
        "quote_built": bool(quote.result.transaction),
        "quote_latency_ms": int(quote.latency_ms),
        "price_impact_bps": impact_bps,
        "sell_fraction": float(fraction),
        "positions_affected": affected,
        "positions_closed": closed,
        "exit_applied": True,
    }

def _selective_wallet_metrics(
    positions: list[CanonicalParserGen4FastpathSelectivePosition],
) -> dict[str, Any]:
    closed = [
        row
        for row in positions
        if row.status == FASTPATH_SELECTIVE_POSITION_CLOSED
        and row.pnl_lamports is not None
        and row.exit_copyable
    ]
    ordered_closed = sorted(
        closed,
        key=lambda row: (_aware(row.closed_at) or _utc_now(), int(row.id or 0)),
    )
    pnl_values = [int(row.pnl_lamports or 0) for row in ordered_closed]
    total_cost = sum(
        int(row.entry_input_lamports) + int(row.allocated_entry_fee_lamports)
        for row in ordered_closed
    )
    gross_profit = sum(value for value in pnl_values if value > 0)
    gross_loss = abs(sum(value for value in pnl_values if value < 0))
    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else (999.0 if gross_profit > 0 else 0.0)
    )
    net_pnl = sum(pnl_values)
    win_rate = (
        100.0 * sum(value > 0 for value in pnl_values) / len(pnl_values)
        if pnl_values
        else 0.0
    )
    cumulative = 0
    peak = 0
    max_drawdown_lamports = 0
    for value in pnl_values:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown_lamports = max(max_drawdown_lamports, peak - cumulative)
    max_drawdown_percent = (
        max_drawdown_lamports / total_cost * 100.0 if total_cost > 0 else 0.0
    )
    best_trade = max(pnl_values) if pnl_values else None
    net_without_best = (net_pnl - best_trade) if best_trade is not None else None
    exit_failure_records = [
        dict(item)
        for row in positions
        for item in list(dict(row.evidence or {}).get("exit_failures") or [])
        if isinstance(item, dict)
    ]
    unique_exit_failures = {
        (str(item.get("signature") or ""), str(item.get("code") or ""))
        for item in exit_failure_records
    }
    exit_failure_breakdown = Counter(
        str(item.get("code") or "UNKNOWN") for item in exit_failure_records
    )
    economics_pass = bool(
        len(closed) >= FASTPATH_SELECTIVE_MIN_CLOSED
        and net_pnl > 0
        and profit_factor >= FASTPATH_SELECTIVE_MIN_PROFIT_FACTOR
        and max_drawdown_percent <= FASTPATH_SELECTIVE_MAX_DRAWDOWN_PERCENT
        and net_without_best is not None
        and net_without_best > 0
    )
    return {
        "entry_count": len(positions),
        "open_position_count": sum(
            row.status
            in {FASTPATH_SELECTIVE_POSITION_OPEN, FASTPATH_SELECTIVE_POSITION_OPEN_PARTIAL}
            for row in positions
        ),
        "closed_trade_count": len(closed),
        "net_pnl_lamports": net_pnl,
        "net_pnl_sol": net_pnl / 1_000_000_000,
        "gross_profit_lamports": gross_profit,
        "gross_loss_lamports": gross_loss,
        "profit_factor": round(profit_factor, 8),
        "win_rate_percent": round(win_rate, 8),
        "maximum_drawdown_lamports": max_drawdown_lamports,
        "maximum_drawdown_percent": round(max_drawdown_percent, 8),
        "best_trade_lamports": best_trade,
        "net_without_best_trade_lamports": net_without_best,
        "technical_exit_failure_count": len(unique_exit_failures),
        "technical_exit_failure_breakdown": dict(sorted(exit_failure_breakdown.items())),
        "economic_gate": {
            "minimum_closed_trades": FASTPATH_SELECTIVE_MIN_CLOSED,
            "minimum_profit_factor": FASTPATH_SELECTIVE_MIN_PROFIT_FACTOR,
            "maximum_drawdown_percent": FASTPATH_SELECTIVE_MAX_DRAWDOWN_PERCENT,
            "requires_positive_net_pnl": True,
            "requires_positive_without_best_trade": True,
            "closed_trades_met": len(closed) >= FASTPATH_SELECTIVE_MIN_CLOSED,
            "net_pnl_positive": net_pnl > 0,
            "profit_factor_pass": profit_factor >= FASTPATH_SELECTIVE_MIN_PROFIT_FACTOR,
            "drawdown_pass": max_drawdown_percent <= FASTPATH_SELECTIVE_MAX_DRAWDOWN_PERCENT,
            "positive_without_best_trade": bool(
                net_without_best is not None and net_without_best > 0
            ),
            "candidate_pass": economics_pass,
        },
    }


def _selective_position_status(
    db: Session,
    *,
    official_events: list[CanonicalParserGen4FastpathShadowEvent],
    recent_limit: int,
) -> dict[str, Any]:
    positions = [
        row
        for row in db.scalars(
            select(CanonicalParserGen4FastpathSelectivePosition).where(
                CanonicalParserGen4FastpathSelectivePosition.scope
                == FASTPATH_SELECTIVE_SCOPE
            )
        )
        if isinstance(row, CanonicalParserGen4FastpathSelectivePosition)
        and str(row.scope or "") == FASTPATH_SELECTIVE_SCOPE
    ]
    m138_events = [
        row
        for row in official_events
        if str(
            dict(row.evidence or {}).get("selective_position_shadow_version") or ""
        )
        == FASTPATH_SELECTIVE_POSITION_VERSION
    ]
    collection_started_at = min(
        (_aware(row.fast_received_at) for row in m138_events),
        default=None,
    )
    wallets = sorted(
        {str(row.wallet_address) for row in positions}
        | {
            str(row.wallet_address)
            for row in m138_events
            if str(row.wallet_address or "") not in {"", "UNRESOLVED"}
        }
    )
    by_wallet: dict[str, Any] = {}
    for wallet in wallets:
        wallet_positions = [
            row for row in positions if str(row.wallet_address) == wallet
        ]
        wallet_events = [
            row for row in m138_events if str(row.wallet_address) == wallet
        ]
        buy_events = [row for row in wallet_events if row.side == "BUY"]
        pam_rejections = [
            row
            for row in buy_events
            if str(row.fast_provisional_rejection_reason or "")
            == "PRICE_ALREADY_MOVED"
        ]
        technical_entry_rejections = [
            row
            for row in buy_events
            if str(row.fast_provisional_rejection_reason or "")
            not in {"", "PRICE_ALREADY_MOVED"}
        ]
        quote_errors = [row for row in buy_events if row.quote_error_code]
        parse_errors = [row for row in wallet_events if row.parse_error_code]
        metrics = _selective_wallet_metrics(wallet_positions)
        technical_entry_failure_count = len(technical_entry_rejections) + len(quote_errors)
        technical_total = (
            technical_entry_failure_count
            + len(parse_errors)
            + int(metrics["technical_exit_failure_count"])
        )
        first_entry = min(
            (_aware(row.opened_at) for row in wallet_positions),
            default=None,
        )
        metrics.update(
            {
                "buy_attempt_count": len(buy_events),
                "accepted_entry_count": len(wallet_positions),
                "entry_acceptance_rate_percent": round(
                    (
                        100.0 * len(wallet_positions) / len(buy_events)
                        if buy_events
                        else 0.0
                    ),
                    8,
                ),
                "pam_rejection_count": len(pam_rejections),
                "pam_rejection_rate_percent": round(
                    (
                        100.0 * len(pam_rejections) / len(buy_events)
                        if buy_events
                        else 0.0
                    ),
                    8,
                ),
                "technical_entry_rejection_count": len(technical_entry_rejections),
                "entry_quote_error_count": len(quote_errors),
                "parse_error_count": len(parse_errors),
                "first_selective_entry_at": first_entry,
                "technical_gate": {
                    "entry_failures": technical_entry_failure_count,
                    "parse_failures": len(parse_errors),
                    "exit_failures": int(metrics["technical_exit_failure_count"]),
                    "total_failures": technical_total,
                    "pass": technical_total == 0,
                },
                "selective_readiness_candidate": bool(
                    metrics["economic_gate"]["candidate_pass"]
                    and technical_total == 0
                ),
            }
        )
        by_wallet[wallet] = metrics

    ordered = sorted(
        positions,
        key=lambda row: (_aware(row.opened_at) or _utc_now(), int(row.id or 0)),
        reverse=True,
    )
    return {
        "version": FASTPATH_SELECTIVE_POSITION_VERSION,
        "scope": FASTPATH_SELECTIVE_SCOPE,
        "strict_forward_only": True,
        "collection_started_at": collection_started_at,
        "strict_forward_event_count": len(m138_events),
        "position_count": len(positions),
        "wallet_count": len(wallets),
        "by_wallet": by_wallet,
        "policy": {
            "pam_rejection_is_selective": True,
            "pam_rejection_changes_m75": False,
            "technical_failures_are_hard_failures": True,
            "economic_minimum_closed_trades": FASTPATH_SELECTIVE_MIN_CLOSED,
            "economic_minimum_profit_factor": FASTPATH_SELECTIVE_MIN_PROFIT_FACTOR,
            "economic_maximum_drawdown_percent": FASTPATH_SELECTIVE_MAX_DRAWDOWN_PERCENT,
            "economic_requires_positive_without_best_trade": True,
        },
        "recent_positions": [
            {
                "position_id": row.position_id,
                "campaign_id": row.campaign_id,
                "wallet": row.wallet_address,
                "token_mint": row.token_mint,
                "entry_signature": row.entry_signature,
                "status": row.status,
                "opened_at": row.opened_at,
                "closed_at": row.closed_at,
                "remaining_token_raw": row.remaining_token_raw,
                "realized_output_lamports": row.realized_output_lamports,
                "pnl_lamports": row.pnl_lamports,
                "return_percent": row.return_percent,
                "last_exit_signature": row.last_exit_signature,
            }
            for row in ordered[: max(1, min(int(recent_limit), 500))]
        ],
        "safety": {
            "dedicated_table_only": True,
            "copyability_position_rows_created": 0,
            "campaign_metrics_mutated": False,
            "candidate_watchlist_positions_created": 0,
            "m75_forward_pass": False,
            "m75_thresholds_changed": False,
            "reject_limit_changed": False,
            "live_execution": False,
            "signer_access": False,
            "submitted_transactions": 0,
            "paper_orders": 0,
        },
    }


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

    selective_position: CanonicalParserGen4FastpathSelectivePosition | None = None
    selective_sell_context: tuple[Any, CanonicalParserGen4CopyabilityCampaign] | None = None

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
            "selective_position_shadow_version": FASTPATH_SELECTIVE_POSITION_VERSION,
            "selective_position_shadow_strict_forward": True,
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
                    if reason is None:
                        conservative_out = _conservative_out_amount(
                            quote.result, int(campaign.slippage_bps)
                        )
                        selective_position = _new_selective_position(
                            event=event,
                            signal=signal,
                            campaign=campaign,
                            quote=quote,
                            conservative_out=conservative_out,
                            deterioration_bps=deterioration,
                            price_impact_bps=impact_bps,
                        )
                        event.evidence = {
                            **dict(event.evidence or {}),
                            "selective_position_shadow": {
                                "version": FASTPATH_SELECTIVE_POSITION_VERSION,
                                "entry_eligible": True,
                                "position_id": selective_position.position_id,
                                "strict_forward_only": True,
                                "mutates_copyability_campaign_metrics": False,
                                "live_execution": False,
                                "signer_access": False,
                            },
                        }
                except JupiterSwapError as exc:
                    _record_jupiter_entry_error(event, exc)
            else:
                event.fast_provisional_rejection_reason = "NOT_A_BUY_SIGNAL"
                if signal.side == "SELL":
                    selective_sell_context = (signal, campaign)
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
            if selective_position is not None:
                db.add(selective_position)
            if selective_sell_context is not None:
                selective_signal, selective_campaign = selective_sell_context
                selective_exit = _apply_selective_sell_shadow(
                    db,
                    event=event,
                    signal=selective_signal,
                    campaign=selective_campaign,
                    jupiter_client=jupiter_client,
                )
                event.evidence = {
                    **dict(event.evidence or {}),
                    "selective_position_shadow": selective_exit,
                }
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




M319_COPYABLE_EDGE_VERSION = "m319-copyable-edge-instrumentation/1"
M319_COPYABLE_EDGE_SCOPE = "M319_COPYABLE_EDGE_FORWARD_INSTRUMENTATION"
M319_COPYABLE_EDGE_EVIDENCE_KEY = "m319_copyable_edge"
M319_COPYABLE_EDGE_RECONCILE_WINDOW_MINUTES = 15
M320_CANDIDATE_ORDER_DIAGNOSTIC_VERSION = "m320-candidate-deferred-order-diagnostic/1"
M320_CANDIDATE_ORDER_DIAGNOSTIC_EVIDENCE_KEY = "m320_candidate_order_diagnostic"


def _m319_elapsed_ms(
    later: datetime | None,
    earlier: datetime | None,
) -> int | None:
    end = _aware(later)
    start = _aware(earlier)
    if end is None or start is None:
        return None
    return max(0, int((end - start).total_seconds() * 1000))


def _m319_source_trade_snapshot(signal: Any) -> dict[str, Any]:
    parser_evidence = dict(getattr(signal, "evidence", None) or {})
    return {
        "side": str(getattr(signal, "side", "") or ""),
        "wallet_address": str(getattr(signal, "wallet_address", "") or ""),
        "token_mint": str(getattr(signal, "token_mint", "") or ""),
        "token_decimals": int(getattr(signal, "token_decimals", 0) or 0),
        "token_delta_raw": int(getattr(signal, "token_delta_raw", 0) or 0),
        "token_pre_raw": int(getattr(signal, "token_pre_raw", 0) or 0),
        "sol_equivalent_delta_lamports": (
            int(signal.sol_equivalent_delta_lamports)
            if getattr(signal, "sol_equivalent_delta_lamports", None) is not None
            else None
        ),
        "network_fee_lamports": int(parser_evidence.get("fee_lamports") or 0),
        "wallet_effective_price_sol": (
            float(signal.wallet_effective_price_sol)
            if getattr(signal, "wallet_effective_price_sol", None) is not None
            else None
        ),
        "sell_fraction": (
            float(signal.sell_fraction)
            if getattr(signal, "sell_fraction", None) is not None
            else None
        ),
    }


def _m319_provider_slot_clock_snapshot(
    provider_slot_clock: dict[str, Any] | None,
    *,
    source_slot: int | None,
    candidate_received_at: datetime,
) -> dict[str, Any] | None:
    if not isinstance(provider_slot_clock, dict) or source_slot is None:
        return None
    try:
        clock_slot = int(provider_slot_clock.get("slot"))
        expected_slot = int(source_slot)
    except (TypeError, ValueError):
        return None
    if clock_slot != expected_slot:
        return None
    try:
        server_timestamp_ms = int(provider_slot_clock.get("server_timestamp_ms"))
        server_time = datetime.fromtimestamp(
            server_timestamp_ms / 1000.0,
            tz=timezone.utc,
        )
    except (TypeError, ValueError, OSError, OverflowError):
        return None
    local_received = None
    raw_local = provider_slot_clock.get("local_received_at_utc")
    if isinstance(raw_local, datetime):
        local_received = _aware(raw_local)
    elif raw_local:
        try:
            local_received = _aware(
                datetime.fromisoformat(str(raw_local).replace("Z", "+00:00"))
            )
        except (TypeError, ValueError):
            local_received = None
    candidate_received = _aware(candidate_received_at) or _utc_now()
    return {
        "origin": "HELIUS_SLOTS_UPDATES_SERVER_TIMESTAMP",
        "source_slot": expected_slot,
        "slot_update_type": str(provider_slot_clock.get("type") or ""),
        "server_timestamp_ms": server_timestamp_ms,
        "server_timestamp_utc": server_time.isoformat(),
        "local_slot_notification_received_at_utc": (
            local_received.isoformat() if local_received is not None else None
        ),
        "provider_slot_to_candidate_receive_ms": _m319_elapsed_ms(
            candidate_received,
            server_time,
        ),
        "local_slot_notice_to_candidate_receive_ms": _m319_elapsed_ms(
            candidate_received,
            local_received,
        ),
        "true_chain_block_time": False,
        "observation_only": True,
    }


def _new_m319_candidate_observation(
    *,
    event: CanonicalParserGen4FastpathShadowEvent,
    signal: Any,
    received_at: datetime,
    parsed_at: datetime,
    provider_slot_clock: dict[str, Any] | None = None,
) -> dict[str, Any]:
    received = _aware(received_at) or _utc_now()
    parsed = _aware(parsed_at) or received
    block_time = _aware(getattr(signal, "block_time", None))
    source_slot = (
        int(getattr(signal, "slot"))
        if getattr(signal, "slot", None) is not None
        else getattr(event, "slot", None)
    )
    slot_clock = _m319_provider_slot_clock_snapshot(
        provider_slot_clock,
        source_slot=source_slot,
        candidate_received_at=received,
    )
    return {
        "version": M319_COPYABLE_EDGE_VERSION,
        "scope": M319_COPYABLE_EDGE_SCOPE,
        "observation_only": True,
        "strict_forward_only": True,
        "backfill": False,
        "automatic_filtering": False,
        "automatic_promotion": False,
        "mutates_m74": False,
        "mutates_m75": False,
        "mutates_m298": False,
        "mutates_m307": False,
        "live_execution": False,
        "paper_execution": False,
        "signer_access": False,
        "source_slot": source_slot,
        "source_provider_slot_time_utc": (
            slot_clock.get("server_timestamp_utc") if slot_clock is not None else None
        ),
        "source_provider_slot_type": (
            slot_clock.get("slot_update_type") if slot_clock is not None else None
        ),
        "provider_slot_to_receive_ms": (
            slot_clock.get("provider_slot_to_candidate_receive_ms")
            if slot_clock is not None
            else None
        ),
        "provider_slot_clock": slot_clock,
        "source_block_time_utc": block_time.isoformat() if block_time is not None else None,
        "source_block_time_origin": (
            "WSS_NOTIFICATION" if block_time is not None else "PENDING_RAW_WEBHOOK_RECONCILIATION"
        ),
        "candidate_received_at_utc": received.isoformat(),
        "parse_completed_at_utc": parsed.isoformat(),
        "chain_to_receive_ms": _m319_elapsed_ms(received, block_time),
        "receive_to_parse_ms": _m319_elapsed_ms(parsed, received),
        "chain_to_parse_ms": _m319_elapsed_ms(parsed, block_time),
        "source_trade": _m319_source_trade_snapshot(signal),
        "follower_entry": None,
        "follower_exit": None,
        "reconciliation": {
            "attempted": False,
            "matched_raw_webhook": False,
        },
    }


def _m319_set_candidate_observation(
    event: CanonicalParserGen4FastpathShadowEvent,
    observation: dict[str, Any],
) -> None:
    evidence = dict(event.evidence or {})
    evidence[M319_COPYABLE_EDGE_EVIDENCE_KEY] = dict(observation)
    event.evidence = evidence



def _m319_jupiter_component_timing_snapshot(
    quote_result: Any,
) -> dict[str, Any] | None:
    raw = getattr(quote_result, "request_timing", None)
    if not isinstance(raw, dict):
        return None
    if str(raw.get("version") or "") != "jupiter-component-timing/1":
        return None

    def endpoint(name: str) -> dict[str, Any] | None:
        value = raw.get(name)
        if not isinstance(value, dict):
            return None
        status_codes: list[int] = []
        for item in value.get("status_codes") or []:
            try:
                status_codes.append(int(item))
            except (TypeError, ValueError):
                continue
        result: dict[str, Any] = {
            "attempts": int(value.get("attempts") or 0),
            "retry_count": int(value.get("retry_count") or 0),
            "shared_pacing_wait_ms": float(
                value.get("shared_pacing_wait_ms") or 0.0
            ),
            "http_round_trip_ms": float(
                value.get("http_round_trip_ms") or 0.0
            ),
            "retry_sleep_requested_ms": float(
                value.get("retry_sleep_requested_ms") or 0.0
            ),
            "endpoint_total_ms": float(
                value.get("endpoint_total_ms") or 0.0
            ),
            "status_codes": status_codes,
            "final_http_status": (
                int(value["final_http_status"])
                if value.get("final_http_status") is not None
                else None
            ),
            "success": bool(value.get("success")),
            "retryable": bool(value.get("retryable")),
            "shared_rate_limit": bool(value.get("shared_rate_limit")),
            "used_persistent_http": bool(value.get("used_persistent_http")),
            "observation_only": True,
        }
        return result

    order = endpoint("order")
    build = endpoint("build")
    if order is None and build is None:
        return None
    try:
        parallel_wall_ms = float(raw.get("parallel_wall_ms") or 0.0)
    except (TypeError, ValueError):
        parallel_wall_ms = 0.0
    return {
        "version": "jupiter-component-timing/1",
        "parallel_wall_ms": parallel_wall_ms,
        "order": order,
        "build": build,
        "observation_only": True,
        "pacing_changed": False,
        "retry_changed": False,
        "request_concurrency_changed": bool(
            raw.get("request_concurrency_changed")
        ),
        "build_priority": bool(raw.get("build_priority")),
        "order_diagnostic_available": bool(
            raw.get("order_diagnostic_available")
        ),
        "order_diagnostic_mode": (
            str(raw.get("order_diagnostic_mode"))
            if raw.get("order_diagnostic_mode")
            else None
        ),
    }

def _m319_update_buy_quote(
    event: CanonicalParserGen4FastpathShadowEvent,
    *,
    quote: Any,
    deterioration_bps: float | None,
    price_impact_bps: float,
    rejection_reason: str | None,
) -> None:
    evidence = dict(event.evidence or {})
    current = evidence.get(M319_COPYABLE_EDGE_EVIDENCE_KEY)
    if not isinstance(current, dict):
        return
    observation = dict(current)
    requested = _aware(getattr(quote, "requested_at", None))
    received = _aware(getattr(quote, "received_at", None))
    candidate_received = _aware(event.fast_received_at)
    block_time = None
    raw_block = observation.get("source_block_time_utc")
    if raw_block:
        try:
            block_time = _aware(datetime.fromisoformat(str(raw_block).replace("Z", "+00:00")))
        except (TypeError, ValueError):
            block_time = None
    provider_slot_time = None
    raw_provider_slot = observation.get("source_provider_slot_time_utc")
    if raw_provider_slot:
        try:
            provider_slot_time = _aware(
                datetime.fromisoformat(str(raw_provider_slot).replace("Z", "+00:00"))
            )
        except (TypeError, ValueError):
            provider_slot_time = None
    observation["follower_entry"] = {
        "quote_requested_at_utc": requested.isoformat() if requested is not None else None,
        "quote_received_at_utc": received.isoformat() if received is not None else None,
        "quote_latency_ms": int(getattr(quote, "latency_ms", 0) or 0),
        "receive_to_quote_request_ms": _m319_elapsed_ms(requested, candidate_received),
        "receive_to_quote_received_ms": _m319_elapsed_ms(received, candidate_received),
        "chain_to_quote_received_ms": _m319_elapsed_ms(received, block_time),
        "provider_slot_to_quote_received_ms": _m319_elapsed_ms(
            received, provider_slot_time
        ),
        "jupiter_component_timing": _m319_jupiter_component_timing_snapshot(
            quote.result
        ),
        "price_deterioration_bps": (
            float(deterioration_bps) if deterioration_bps is not None else None
        ),
        "price_impact_bps": float(price_impact_bps),
        "transaction_built": bool(getattr(quote.result, "transaction", None)),
        "rejection_reason": rejection_reason,
    }
    evidence[M319_COPYABLE_EDGE_EVIDENCE_KEY] = observation
    event.evidence = evidence


def _m319_update_sell_shadow(
    event: CanonicalParserGen4FastpathShadowEvent,
    sell_evidence: dict[str, Any],
) -> None:
    evidence = dict(event.evidence or {})
    current = evidence.get(M319_COPYABLE_EDGE_EVIDENCE_KEY)
    if not isinstance(current, dict):
        return
    observation = dict(current)
    observation["follower_exit"] = {
        "quote_attempted": bool(sell_evidence.get("quote_attempted")),
        "quote_built": bool(sell_evidence.get("quote_built")),
        "quote_latency_ms": sell_evidence.get("quote_latency_ms"),
        "price_impact_bps": sell_evidence.get("price_impact_bps"),
        "exit_applied": bool(sell_evidence.get("exit_applied")),
        "positions_closed": int(sell_evidence.get("positions_closed") or 0),
        "reason": sell_evidence.get("reason"),
        "quote_error": sell_evidence.get("quote_error"),
    }
    evidence[M319_COPYABLE_EDGE_EVIDENCE_KEY] = observation
    event.evidence = evidence


M314_CANDIDATE_ROUNDTRIP_VERSION = "m314-candidate-forward-roundtrip-shadow/1"
M314_CANDIDATE_ROUNDTRIP_SCOPE = "M314_CANDIDATE_ROUNDTRIP"
M314_CANDIDATE_ROUNDTRIP_GATE_ARMED = False
M314_CANDIDATE_ROUNDTRIP_MIN_CLOSED = 10
M314_CANDIDATE_ROUNDTRIP_MIN_PROFIT_FACTOR = 1.30
M314_CANDIDATE_ROUNDTRIP_MAX_DRAWDOWN_PERCENT = 15.0
M314_CANDIDATE_ROUNDTRIP_EVIDENCE_KEY = "m314_candidate_roundtrip"
M314_CANDIDATE_EXIT_RECOVERY_VERSION = "m314-candidate-exit-autonomous-recovery-shadow/1"
M314_CANDIDATE_EXIT_RECOVERY_MAX_ATTEMPTS = PROMOTED_EXIT_RECOVERY_MAX_ATTEMPTS
M314_CANDIDATE_EXIT_RECOVERY_MAX_AGE_SECONDS = PROMOTED_EXIT_RECOVERY_MAX_AGE_SECONDS
M314_CANDIDATE_EXIT_RECOVERY_BACKOFF_SECONDS = PROMOTED_EXIT_RECOVERY_BACKOFF_SECONDS
M314_CANDIDATE_EXIT_RECOVERY_TICK_SECONDS = PROMOTED_EXIT_RECOVERY_TICK_SECONDS
M314_CANDIDATE_EXIT_RECOVERY_SCAN_LIMIT = 1000


def _candidate_roundtrip_fee_lamports() -> int:
    return int(
        getattr(
            settings,
            "CANONICAL_PARSER_GEN4_COPYABILITY_ESTIMATED_NETWORK_FEE_LAMPORTS",
            100_000,
        )
    )


def _candidate_roundtrip_state(row: Any) -> dict[str, Any] | None:
    evidence = dict(getattr(row, "evidence", None) or {})
    value = evidence.get(M314_CANDIDATE_ROUNDTRIP_EVIDENCE_KEY)
    if not isinstance(value, dict):
        return None
    if str(value.get("version") or "") != M314_CANDIDATE_ROUNDTRIP_VERSION:
        return None
    if str(value.get("scope") or "") != M314_CANDIDATE_ROUNDTRIP_SCOPE:
        return None
    return dict(value)


def _set_candidate_roundtrip_state(row: Any, state: dict[str, Any]) -> None:
    evidence = dict(getattr(row, "evidence", None) or {})
    evidence[M314_CANDIDATE_ROUNDTRIP_EVIDENCE_KEY] = dict(state)
    row.evidence = evidence


def _new_candidate_roundtrip_state(
    *,
    event: CanonicalParserGen4FastpathShadowEvent,
    signal: Any,
    policy: dict[str, Any],
    quote: Any,
    conservative_out: int,
    deterioration_bps: float | None,
    price_impact_bps: float,
) -> dict[str, Any]:
    opened_at = _aware(quote.received_at) or _utc_now()
    fee = _candidate_roundtrip_fee_lamports()
    return {
        "version": M314_CANDIDATE_ROUNDTRIP_VERSION,
        "scope": M314_CANDIDATE_ROUNDTRIP_SCOPE,
        "gate_armed": False,
        "strict_forward_only": True,
        "backfill": False,
        "status": "OPEN",
        "position_id": str(uuid4()),
        "entry_fast_event_id": str(event.event_id),
        "wallet_address": str(signal.wallet_address),
        "token_mint": str(signal.token_mint),
        "token_decimals": int(signal.token_decimals),
        "entry_signature": str(signal.signature),
        "entry_received_at": (_aware(event.fast_received_at) or _utc_now()).isoformat(),
        "opened_at": opened_at.isoformat(),
        "closed_at": None,
        "entry_quote_latency_ms": int(quote.latency_ms),
        "entry_price_deterioration_bps": deterioration_bps,
        "entry_price_impact_bps": float(price_impact_bps),
        "entry_transaction_built": bool(quote.result.transaction),
        "entry_input_lamports": int(quote.result.in_amount),
        "entry_output_token_raw": int(conservative_out),
        "remaining_token_raw": int(conservative_out),
        "allocated_entry_fee_lamports": fee,
        "realized_output_lamports": 0,
        "allocated_exit_fee_lamports": 0,
        "pnl_lamports": None,
        "return_percent": None,
        "last_exit_signature": None,
        "exit_quote_latency_ms": None,
        "exit_price_impact_bps": None,
        "exit_transaction_built": False,
        "exit_copyable": False,
        "close_reason": None,
        "entry_quote": {
            **dict(quote.sanitized or {}),
            "expected_out_amount": int(quote.result.out_amount),
            "conservative_out_amount": int(conservative_out),
            "slippage_haircut_applied": True,
        },
        "exit_quotes": [],
        "exit_failures": [],
        "policy_snapshot": {
            "simulated_input_lamports": int(policy["simulated_input_lamports"]),
            "slippage_bps": int(policy["slippage_bps"]),
            "max_quote_latency_ms": int(policy["max_quote_latency_ms"]),
            "max_price_impact_bps": float(policy["max_price_impact_bps"]),
            "max_price_deterioration_bps": float(policy["max_price_deterioration_bps"]),
            "estimated_network_fee_lamports": fee,
        },
        "mutates_m300": False,
        "mutates_m298": False,
        "mutates_m307": False,
        "live_execution": False,
        "paper_execution": False,
        "signer_access": False,
    }


def _candidate_roundtrip_record_exit_failure(
    rows: list[CanonicalParserGen4FastpathShadowEvent],
    *,
    signature: str,
    code: str,
    observed_at: datetime,
    details: dict[str, Any] | None = None,
    recovery_id: str | None = None,
) -> None:
    for row in rows:
        state = _candidate_roundtrip_state(row)
        if state is None:
            continue
        failures = [
            dict(item)
            for item in list(state.get("exit_failures") or [])
            if isinstance(item, dict)
        ]
        record: dict[str, Any] = {
            "signature": str(signature),
            "code": str(code),
            "observed_at": observed_at.isoformat(),
        }
        if details:
            record["details"] = dict(details)
        if recovery_id:
            record["recovery_id"] = str(recovery_id)
            record["terminal_after_autonomous_recovery"] = True
        failures.append(record)
        state["exit_failures"] = failures[-100:]
        _set_candidate_roundtrip_state(row, state)


def _candidate_roundtrip_recovery_history_append(
    state: dict[str, Any], item: dict[str, Any]
) -> None:
    history = [
        dict(value)
        for value in list(state.get("exit_recovery_history") or [])
        if isinstance(value, dict)
    ]
    history.append(dict(item))
    state["exit_recovery_history"] = history[-100:]


def _candidate_roundtrip_schedule_exit_recovery(
    rows: list[CanonicalParserGen4FastpathShadowEvent],
    *,
    signature: str,
    sell_fraction: float,
    sold_allocations: list[int],
    observed_at: datetime,
    error: JupiterSwapError,
) -> dict[str, Any]:
    if len(rows) != len(sold_allocations):
        raise ValueError("M314_EXIT_RECOVERY_ALLOCATION_LENGTH_MISMATCH")
    recovery_id = str(uuid4())
    now = _aware(observed_at) or _utc_now()
    next_retry = now + timedelta(seconds=M314_CANDIDATE_EXIT_RECOVERY_BACKOFF_SECONDS[0])
    error_snapshot = promoted_exit_error_snapshot(error)
    scheduled = 0
    requested_total = 0
    for row, sold_raw in zip(rows, sold_allocations):
        state = _candidate_roundtrip_state(row)
        if state is None:
            continue
        requested_raw = max(
            0, min(int(state.get("remaining_token_raw") or 0), int(sold_raw))
        )
        if requested_raw <= 0:
            continue
        target_remaining = max(
            0, int(state.get("remaining_token_raw") or 0) - requested_raw
        )
        pending = {
            "version": M314_CANDIDATE_EXIT_RECOVERY_VERSION,
            "state": "PENDING",
            "recovery_id": recovery_id,
            "source_signature": str(signature),
            "source_sell_fraction": float(sell_fraction),
            "requested_sell_token_raw": requested_raw,
            "target_remaining_token_raw": target_remaining,
            "scheduled_at_utc": now.isoformat(),
            "next_retry_at_utc": next_retry.isoformat(),
            "recovery_attempts": 0,
            "max_recovery_attempts": M314_CANDIDATE_EXIT_RECOVERY_MAX_ATTEMPTS,
            "max_recovery_age_seconds": M314_CANDIDATE_EXIT_RECOVERY_MAX_AGE_SECONDS,
            "initial_error": error_snapshot,
            "last_error": error_snapshot,
            "live_execution": False,
            "paper_execution": False,
            "signer_access": False,
            "transaction_submission": False,
        }
        state["pending_exit_recovery"] = pending
        _candidate_roundtrip_recovery_history_append(
            state,
            {
                "recovery_id": recovery_id,
                "state": "SCHEDULED",
                "observed_at_utc": now.isoformat(),
                "source_signature": str(signature),
                "requested_sell_token_raw": requested_raw,
                "target_remaining_token_raw": target_remaining,
                "error": error_snapshot,
            },
        )
        _set_candidate_roundtrip_state(row, state)
        scheduled += 1
        requested_total += requested_raw
    return {
        "scheduled": scheduled > 0,
        "recovery_id": recovery_id,
        "positions_scheduled": scheduled,
        "requested_sell_token_raw": requested_total,
        "next_retry_at_utc": next_retry.isoformat(),
        "max_recovery_attempts": M314_CANDIDATE_EXIT_RECOVERY_MAX_ATTEMPTS,
        "max_recovery_age_seconds": M314_CANDIDATE_EXIT_RECOVERY_MAX_AGE_SECONDS,
        "initial_error": error_snapshot,
        "live_execution": False,
        "paper_execution": False,
        "signer_access": False,
        "transaction_submission": False,
    }


def _candidate_roundtrip_pending(state: dict[str, Any]) -> dict[str, Any] | None:
    raw = state.get("pending_exit_recovery")
    if not isinstance(raw, dict):
        return None
    if str(raw.get("state") or "").upper() != "PENDING":
        return None
    if str(raw.get("version") or "") != M314_CANDIDATE_EXIT_RECOVERY_VERSION:
        return None
    if not str(raw.get("recovery_id") or "").strip():
        return None
    return dict(raw)


def _candidate_roundtrip_mark_recovery_state(
    row: CanonicalParserGen4FastpathShadowEvent,
    *,
    state_name: str,
    observed_at: datetime,
    extra: dict[str, Any] | None = None,
) -> None:
    state = _candidate_roundtrip_state(row)
    if state is None:
        return
    pending = dict(state.get("pending_exit_recovery") or {})
    if not pending:
        return
    pending["state"] = str(state_name)
    pending["resolved_at_utc"] = observed_at.isoformat()
    if extra:
        pending.update(dict(extra))
    state["pending_exit_recovery"] = pending
    _candidate_roundtrip_recovery_history_append(
        state,
        {
            "recovery_id": pending.get("recovery_id"),
            "state": str(state_name),
            "observed_at_utc": observed_at.isoformat(),
            **(dict(extra) if extra else {}),
        },
    )
    _set_candidate_roundtrip_state(row, state)


def _candidate_roundtrip_next_backoff(attempt_number: int) -> float:
    index = max(
        0,
        min(
            int(attempt_number),
            len(M314_CANDIDATE_EXIT_RECOVERY_BACKOFF_SECONDS) - 1,
        ),
    )
    return float(M314_CANDIDATE_EXIT_RECOVERY_BACKOFF_SECONDS[index])


def _candidate_roundtrip_terminalize_recovery(
    rows: list[CanonicalParserGen4FastpathShadowEvent],
    *,
    pending_by_position: dict[str, dict[str, Any]],
    observed_at: datetime,
    code: str,
    details: dict[str, Any] | None,
    terminal_state: str,
) -> None:
    for row in rows:
        state = _candidate_roundtrip_state(row)
        if state is None:
            continue
        key = str(state.get("position_id") or getattr(row, "event_id", ""))
        pending = pending_by_position[key]
        _candidate_roundtrip_record_exit_failure(
            [row],
            signature=str(pending.get("source_signature") or ""),
            code=str(code),
            observed_at=observed_at,
            details=details,
            recovery_id=str(pending.get("recovery_id") or ""),
        )
        _candidate_roundtrip_mark_recovery_state(
            row,
            state_name=terminal_state,
            observed_at=observed_at,
            extra={"terminal_code": str(code), "terminal_details": details or {}},
        )


def _candidate_roundtrip_apply_allocations(
    rows: list[CanonicalParserGen4FastpathShadowEvent],
    *,
    signal: Any,
    quote: Any,
    conservative_out: int,
    amount_to_sell: int,
    fee_lamports: int,
) -> dict[str, int]:
    states = [_candidate_roundtrip_state(row) for row in rows]
    if any(state is None for state in states):
        raise ValueError("M314_ROUNDTRIP_STATE_MISSING")

    concrete_states = [state for state in states if state is not None]
    weights = [int(state["remaining_token_raw"]) for state in concrete_states]
    sold_allocations = _allocate_integer(int(amount_to_sell), weights)
    out_allocations = _allocate_integer(int(conservative_out), sold_allocations)
    fee_allocations = _allocate_integer(int(fee_lamports), sold_allocations)
    impact_bps = max(0.0, float(quote.result.price_impact_percent) * 100.0)
    fraction = float(signal.sell_fraction)

    affected = 0
    closed = 0
    for row, state, sold_raw, out_lamports, allocated_fee in zip(
        rows, concrete_states, sold_allocations, out_allocations, fee_allocations
    ):
        if int(sold_raw) <= 0:
            continue
        affected += 1
        state["remaining_token_raw"] = max(
            0, int(state["remaining_token_raw"]) - int(sold_raw)
        )
        state["realized_output_lamports"] = (
            int(state.get("realized_output_lamports") or 0) + int(out_lamports)
        )
        state["allocated_exit_fee_lamports"] = (
            int(state.get("allocated_exit_fee_lamports") or 0) + int(allocated_fee)
        )
        state["last_exit_signature"] = str(signal.signature)
        state["exit_quote_latency_ms"] = int(quote.latency_ms)
        state["exit_price_impact_bps"] = float(impact_bps)
        state["exit_transaction_built"] = bool(quote.result.transaction)
        state["exit_copyable"] = True
        exit_quotes = [
            dict(item)
            for item in list(state.get("exit_quotes") or [])
            if isinstance(item, dict)
        ]
        exit_quotes.append(
            {
                "signature": str(signal.signature),
                "sell_fraction": fraction,
                "sold_token_raw": int(sold_raw),
                "out_lamports": int(out_lamports),
                "allocated_fee_lamports": int(allocated_fee),
                "quote": {
                    **dict(quote.sanitized or {}),
                    "expected_out_amount": int(quote.result.out_amount),
                    "conservative_out_amount": int(conservative_out),
                    "slippage_haircut_applied": True,
                },
                "quote_requested_at": quote.requested_at.isoformat(),
                "quote_received_at": quote.received_at.isoformat(),
            }
        )
        state["exit_quotes"] = exit_quotes[-100:]
        dust_limit = max(1, int(int(state["entry_output_token_raw"]) * 0.001))
        if int(state["remaining_token_raw"]) <= dust_limit or fraction >= 0.999:
            state["remaining_token_raw"] = 0
            state["status"] = "CLOSED"
            state["closed_at"] = (_aware(quote.received_at) or _utc_now()).isoformat()
            state["close_reason"] = "MIRRORED_WALLET_EXIT"
            cost = int(state["entry_input_lamports"]) + int(
                state["allocated_entry_fee_lamports"]
            )
            proceeds = int(state["realized_output_lamports"]) - int(
                state["allocated_exit_fee_lamports"]
            )
            pnl = proceeds - cost
            state["pnl_lamports"] = int(pnl)
            state["return_percent"] = (pnl / cost * 100.0) if cost > 0 else None
            closed += 1
        else:
            state["status"] = "OPEN_PARTIAL"
        _set_candidate_roundtrip_state(row, state)
    return {"positions_affected": affected, "positions_closed": closed}


def _apply_candidate_roundtrip_sell_shadow(
    db: Session,
    *,
    event: CanonicalParserGen4FastpathShadowEvent,
    signal: Any,
    policy: dict[str, Any],
    jupiter_client: JupiterSwapClient,
) -> dict[str, Any]:
    candidates = list(
        db.scalars(
            select(CanonicalParserGen4FastpathShadowEvent)
            .where(
                CanonicalParserGen4FastpathShadowEvent.wallet_address
                == str(signal.wallet_address),
                CanonicalParserGen4FastpathShadowEvent.token_mint
                == str(signal.token_mint),
                CanonicalParserGen4FastpathShadowEvent.fast_received_at
                < (_aware(event.fast_received_at) or _utc_now()),
            )
            .order_by(
                CanonicalParserGen4FastpathShadowEvent.fast_received_at,
                CanonicalParserGen4FastpathShadowEvent.id,
            )
            .with_for_update()
        )
    )
    positions = []
    for row in candidates:
        if not _is_candidate_event(row):
            continue
        state = _candidate_roundtrip_state(row)
        if state is None:
            continue
        if str(state.get("status") or "") not in {"OPEN", "OPEN_PARTIAL"}:
            continue
        if int(state.get("remaining_token_raw") or 0) <= 0:
            continue
        positions.append(row)

    base = {
        "version": M314_CANDIDATE_ROUNDTRIP_VERSION,
        "scope": M314_CANDIDATE_ROUNDTRIP_SCOPE,
        "side": "SELL",
        "open_positions_found": len(positions),
        "quote_attempted": False,
        "exit_applied": False,
        "positions_closed": 0,
        "gate_armed": False,
        "strict_forward_only": True,
        "backfill": False,
        "mutates_m300": False,
        "mutates_m298": False,
        "mutates_m307": False,
        "live_execution": False,
        "paper_execution": False,
        "signer_access": False,
    }
    if not positions:
        return {**base, "reason": "NO_OPEN_M314_CANDIDATE_POSITION"}

    fraction = signal.sell_fraction
    if fraction is None or float(fraction) <= 0:
        return {**base, "reason": "SELL_FRACTION_UNAVAILABLE"}

    weights = [
        int((_candidate_roundtrip_state(row) or {}).get("remaining_token_raw") or 0)
        for row in positions
    ]
    total_remaining = sum(weights)
    if total_remaining <= 0:
        return {**base, "reason": "NO_REMAINING_M314_CANDIDATE_TOKEN"}

    amount_to_sell = min(
        total_remaining,
        max(1, int(total_remaining * float(fraction))),
    )
    sold_allocations = _allocate_integer(int(amount_to_sell), weights)

    try:
        quote = _quote(
            input_mint=str(signal.token_mint),
            output_mint=SOL_MINT,
            amount_raw=int(amount_to_sell),
            slippage_bps=int(policy["slippage_bps"]),
            client=jupiter_client,
        )
    except JupiterSwapError as exc:
        code = str(exc.code)
        observed_at = _aware(event.fast_received_at) or _utc_now()
        error_details = promoted_exit_error_snapshot(exc)
        if is_recoverable_promoted_exit_error(exc):
            recovery = _candidate_roundtrip_schedule_exit_recovery(
                positions,
                signature=str(signal.signature),
                sell_fraction=float(fraction),
                sold_allocations=sold_allocations,
                observed_at=observed_at,
                error=exc,
            )
            return {
                **base,
                "quote_attempted": True,
                "quote_error": code,
                "reason": "EXIT_RECOVERY_SCHEDULED",
                "autonomous_exit_recovery": recovery,
            }
        _candidate_roundtrip_record_exit_failure(
            positions,
            signature=str(signal.signature),
            code=code,
            observed_at=observed_at,
            details=error_details,
        )
        return {
            **base,
            "quote_attempted": True,
            "quote_error": code,
            "quote_error_details": error_details,
            "reason": "EXIT_QUOTE_ERROR",
        }

    conservative_out = _conservative_out_amount(
        quote.result, int(policy["slippage_bps"])
    )
    impact_bps = max(0.0, float(quote.result.price_impact_percent) * 100.0)
    rejection = _selective_exit_rejection(
        policy,
        quote_latency_ms=int(quote.latency_ms),
        out_amount=int(quote.result.out_amount),
        transaction_built=bool(quote.result.transaction),
        price_impact_bps=impact_bps,
    )
    if rejection is not None:
        _candidate_roundtrip_record_exit_failure(
            positions,
            signature=str(signal.signature),
            code=rejection,
            observed_at=_aware(quote.received_at) or _utc_now(),
        )
        return {
            **base,
            "quote_attempted": True,
            "quote_built": bool(quote.result.transaction),
            "quote_latency_ms": int(quote.latency_ms),
            "price_impact_bps": impact_bps,
            "reason": rejection,
        }

    applied = _candidate_roundtrip_apply_allocations(
        positions,
        signal=signal,
        quote=quote,
        conservative_out=int(conservative_out),
        amount_to_sell=int(amount_to_sell),
        fee_lamports=_candidate_roundtrip_fee_lamports(),
    )
    return {
        **base,
        "quote_attempted": True,
        "quote_built": bool(quote.result.transaction),
        "quote_latency_ms": int(quote.latency_ms),
        "price_impact_bps": impact_bps,
        "sell_fraction": float(fraction),
        **applied,
        "exit_applied": True,
    }


def _recover_candidate_roundtrip_rows(
    rows: list[CanonicalParserGen4FastpathShadowEvent],
    *,
    jupiter_client: JupiterSwapClient,
    now: datetime | None = None,
) -> dict[str, Any]:
    observed = _aware(now) or _utc_now()
    due: dict[str, list[CanonicalParserGen4FastpathShadowEvent]] = {}
    pending_by_position: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not _is_candidate_event(row):
            continue
        state = _candidate_roundtrip_state(row)
        if state is None:
            continue
        if str(state.get("status") or "") not in {"OPEN", "OPEN_PARTIAL"}:
            continue
        if int(state.get("remaining_token_raw") or 0) <= 0:
            continue
        pending = _candidate_roundtrip_pending(state)
        if pending is None:
            continue
        next_retry = _aware(
            datetime.fromisoformat(str(pending.get("next_retry_at_utc")).replace("Z", "+00:00"))
            if pending.get("next_retry_at_utc")
            else None
        )
        if next_retry is not None and observed < next_retry:
            continue
        recovery_id = str(pending["recovery_id"])
        due.setdefault(recovery_id, []).append(row)
        key = str(state.get("position_id") or getattr(row, "event_id", ""))
        pending_by_position[key] = pending

    summary = {
        "version": M314_CANDIDATE_EXIT_RECOVERY_VERSION,
        "checked_open_positions": sum(
            1
            for row in rows
            if _is_candidate_event(row)
            and (_candidate_roundtrip_state(row) or {}).get("status") in {"OPEN", "OPEN_PARTIAL"}
        ),
        "due_recovery_groups": len(due),
        "attempted_groups": 0,
        "recovered_groups": 0,
        "superseded_groups": 0,
        "rescheduled_groups": 0,
        "terminal_groups": 0,
        "positions_closed": 0,
        "positions_partially_reduced": 0,
        "jupiter_quote_attempted": 0,
        "live_execution": False,
        "paper_execution": False,
        "signer_access": False,
        "transaction_submission": False,
        "backfill": False,
    }

    for recovery_id, positions in due.items():
        summary["attempted_groups"] += 1
        first_state = _candidate_roundtrip_state(positions[0]) or {}
        first_key = str(
            first_state.get("position_id") or getattr(positions[0], "event_id", "")
        )
        first_pending = pending_by_position[first_key]
        desired_raw: list[int] = []
        all_satisfied = True
        for row in positions:
            state = _candidate_roundtrip_state(row) or {}
            key = str(state.get("position_id") or getattr(row, "event_id", ""))
            pending = pending_by_position[key]
            target = max(0, int(pending.get("target_remaining_token_raw") or 0))
            desired = max(0, int(state.get("remaining_token_raw") or 0) - target)
            desired_raw.append(desired)
            if desired > 0:
                all_satisfied = False
        if all_satisfied:
            for row in positions:
                _candidate_roundtrip_mark_recovery_state(
                    row,
                    state_name="SUPERSEDED_BY_LATER_EXIT",
                    observed_at=observed,
                )
            summary["superseded_groups"] += 1
            continue

        scheduled_at_raw = first_pending.get("scheduled_at_utc")
        scheduled_at = (
            _aware(
                datetime.fromisoformat(str(scheduled_at_raw).replace("Z", "+00:00"))
            )
            if scheduled_at_raw
            else observed
        ) or observed
        age_seconds = max(0.0, (observed - scheduled_at).total_seconds())
        previous_attempts = max(0, int(first_pending.get("recovery_attempts") or 0))
        if (
            previous_attempts >= M314_CANDIDATE_EXIT_RECOVERY_MAX_ATTEMPTS
            or age_seconds > M314_CANDIDATE_EXIT_RECOVERY_MAX_AGE_SECONDS
        ):
            _candidate_roundtrip_terminalize_recovery(
                positions,
                pending_by_position=pending_by_position,
                observed_at=observed,
                code="EXIT_RECOVERY_EXHAUSTED",
                details={
                    "recovery_attempts": previous_attempts,
                    "age_seconds": age_seconds,
                    "last_error": first_pending.get("last_error"),
                },
                terminal_state="TERMINAL_EXHAUSTED",
            )
            summary["terminal_groups"] += 1
            continue

        amount_to_sell = sum(desired_raw)
        if amount_to_sell <= 0:
            continue
        policy = dict(first_state.get("policy_snapshot") or {})
        summary["jupiter_quote_attempted"] += 1
        try:
            quote = _quote(
                input_mint=str(first_state.get("token_mint") or ""),
                output_mint=SOL_MINT,
                amount_raw=int(amount_to_sell),
                slippage_bps=int(policy["slippage_bps"]),
                client=jupiter_client,
            )
        except JupiterSwapError as exc:
            error = promoted_exit_error_snapshot(exc)
            attempts = previous_attempts + 1
            terminal = (
                not is_recoverable_promoted_exit_error(exc)
                or attempts >= M314_CANDIDATE_EXIT_RECOVERY_MAX_ATTEMPTS
                or age_seconds >= M314_CANDIDATE_EXIT_RECOVERY_MAX_AGE_SECONDS
            )
            if terminal:
                _candidate_roundtrip_terminalize_recovery(
                    positions,
                    pending_by_position=pending_by_position,
                    observed_at=observed,
                    code=str(exc.code),
                    details={
                        "recovery_attempts": attempts,
                        "age_seconds": age_seconds,
                        "jupiter_error": error,
                    },
                    terminal_state="TERMINAL_JUPITER_FAILURE",
                )
                summary["terminal_groups"] += 1
            else:
                next_retry = observed + timedelta(
                    seconds=_candidate_roundtrip_next_backoff(attempts)
                )
                for row in positions:
                    state = _candidate_roundtrip_state(row)
                    if state is None:
                        continue
                    pending = dict(state.get("pending_exit_recovery") or {})
                    pending["recovery_attempts"] = attempts
                    pending["last_attempt_at_utc"] = observed.isoformat()
                    pending["next_retry_at_utc"] = next_retry.isoformat()
                    pending["last_error"] = error
                    state["pending_exit_recovery"] = pending
                    _candidate_roundtrip_recovery_history_append(
                        state,
                        {
                            "recovery_id": recovery_id,
                            "state": "RETRY_FAILED_RESCHEDULED",
                            "observed_at_utc": observed.isoformat(),
                            "attempt": attempts,
                            "next_retry_at_utc": next_retry.isoformat(),
                            "error": error,
                        },
                    )
                    _set_candidate_roundtrip_state(row, state)
                summary["rescheduled_groups"] += 1
            continue

        conservative_out = _conservative_out_amount(
            quote.result, int(policy["slippage_bps"])
        )
        impact_bps = max(0.0, float(quote.result.price_impact_percent) * 100.0)
        rejection = _selective_exit_rejection(
            policy,
            quote_latency_ms=int(quote.latency_ms),
            out_amount=int(quote.result.out_amount),
            transaction_built=bool(quote.result.transaction),
            price_impact_bps=impact_bps,
        )
        if rejection is not None:
            _candidate_roundtrip_terminalize_recovery(
                positions,
                pending_by_position=pending_by_position,
                observed_at=_aware(quote.received_at) or observed,
                code=rejection,
                details={
                    "quote_latency_ms": int(quote.latency_ms),
                    "price_impact_bps": impact_bps,
                    "transaction_built": bool(quote.result.transaction),
                },
                terminal_state="TERMINAL_POLICY_REJECTION",
            )
            summary["terminal_groups"] += 1
            continue

        source_signature = str(first_pending.get("source_signature") or "")
        source_fraction = float(first_pending.get("source_sell_fraction") or 0.0)
        applied = _candidate_roundtrip_apply_allocations(
            positions,
            signal=SimpleNamespace(
                signature=source_signature, sell_fraction=source_fraction
            ),
            quote=quote,
            conservative_out=int(conservative_out),
            amount_to_sell=int(amount_to_sell),
            fee_lamports=_candidate_roundtrip_fee_lamports(),
        )
        recovered_at = _aware(quote.received_at) or observed
        for row in positions:
            state = _candidate_roundtrip_state(row)
            if state is None:
                continue
            quotes = [
                dict(item)
                for item in list(state.get("exit_quotes") or [])
                if isinstance(item, dict)
            ]
            if quotes and str(quotes[-1].get("signature") or "") == source_signature:
                quotes[-1]["autonomous_exit_recovery"] = True
                quotes[-1]["recovery_id"] = recovery_id
                state["exit_quotes"] = quotes[-100:]
            if str(state.get("status") or "") == "CLOSED":
                state["close_reason"] = "MIRRORED_WALLET_EXIT_RECOVERED"
            _set_candidate_roundtrip_state(row, state)
            _candidate_roundtrip_mark_recovery_state(
                row,
                state_name="RECOVERED",
                observed_at=recovered_at,
                extra={
                    "quote_latency_ms": int(quote.latency_ms),
                    "price_impact_bps": impact_bps,
                },
            )
        summary["recovered_groups"] += 1
        summary["positions_closed"] += int(applied.get("positions_closed") or 0)
        summary["positions_partially_reduced"] += max(
            0,
            int(applied.get("positions_affected") or 0)
            - int(applied.get("positions_closed") or 0),
        )

    return summary


def recover_candidate_roundtrip_exits(
    db: Session,
    *,
    jupiter_client: JupiterSwapClient,
    now: datetime | None = None,
    limit: int = M314_CANDIDATE_EXIT_RECOVERY_SCAN_LIMIT,
) -> dict[str, Any]:
    rows = list(
        db.scalars(
            select(CanonicalParserGen4FastpathShadowEvent)
            .where(CanonicalParserGen4FastpathShadowEvent.side == "BUY")
            .order_by(
                CanonicalParserGen4FastpathShadowEvent.fast_received_at.desc(),
                CanonicalParserGen4FastpathShadowEvent.id.desc(),
            )
            .limit(max(1, min(int(limit), M314_CANDIDATE_EXIT_RECOVERY_SCAN_LIMIT)))
            .with_for_update()
        )
    )
    return _recover_candidate_roundtrip_rows(
        rows,
        jupiter_client=jupiter_client,
        now=now,
    )



def _candidate_roundtrip_metrics_from_events(
    events: list[Any],
    *,
    recent_limit: int = 100,
) -> dict[str, Any]:
    entries = []
    for row in events:
        state = _candidate_roundtrip_state(row)
        if state is not None:
            entries.append((row, state))

    closed = [
        (row, state)
        for row, state in entries
        if str(state.get("status") or "") == "CLOSED"
        and state.get("pnl_lamports") is not None
        and bool(state.get("exit_copyable"))
    ]
    closed.sort(
        key=lambda item: (
            str(item[1].get("closed_at") or ""),
            str(getattr(item[0], "event_id", "") or ""),
        )
    )
    pnl_values = [int(state["pnl_lamports"]) for _, state in closed]
    total_cost = sum(
        int(state["entry_input_lamports"])
        + int(state["allocated_entry_fee_lamports"])
        for _, state in closed
    )
    gross_profit = sum(value for value in pnl_values if value > 0)
    gross_loss = abs(sum(value for value in pnl_values if value < 0))
    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else (999.0 if gross_profit > 0 else 0.0)
    )
    net_pnl = sum(pnl_values)
    cumulative = 0
    peak = 0
    max_drawdown_lamports = 0
    for value in pnl_values:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown_lamports = max(max_drawdown_lamports, peak - cumulative)
    max_drawdown_percent = (
        max_drawdown_lamports / total_cost * 100.0 if total_cost > 0 else 0.0
    )
    realized_equity_metrics = m316_closed_trade_metrics(
        [state for _, state in closed]
    )
    realized_equity_drawdown_percent = float(
        realized_equity_metrics["maximum_realized_equity_drawdown_percent"]
    )
    best_trade = max(pnl_values) if pnl_values else None
    net_without_best = (net_pnl - best_trade) if best_trade is not None else None
    failures = [
        dict(item)
        for _, state in entries
        for item in list(state.get("exit_failures") or [])
        if isinstance(item, dict)
    ]
    unique_failures = {
        (str(item.get("signature") or ""), str(item.get("code") or ""))
        for item in failures
    }
    open_position_count = sum(
        str(state.get("status") or "") in {"OPEN", "OPEN_PARTIAL"}
        and int(state.get("remaining_token_raw") or 0) > 0
        for _, state in entries
    )
    economic_gate = {
        "minimum_closed_trades": len(closed) >= M314_CANDIDATE_ROUNDTRIP_MIN_CLOSED,
        "positive_net_pnl": net_pnl > 0,
        "minimum_profit_factor": profit_factor >= M314_CANDIDATE_ROUNDTRIP_MIN_PROFIT_FACTOR,
        "maximum_realized_equity_drawdown": (
            realized_equity_drawdown_percent
            <= M314_CANDIDATE_ROUNDTRIP_MAX_DRAWDOWN_PERCENT
        ),
        "positive_net_without_best_trade": (
            net_without_best is not None and net_without_best > 0
        ),
        "zero_technical_exit_failures": len(unique_failures) == 0,
        "zero_open_positions": open_position_count == 0,
    }
    economics_pass = bool(entries) and all(economic_gate.values())
    recent = sorted(
        entries,
        key=lambda item: (
            str(item[1].get("opened_at") or ""),
            str(getattr(item[0], "event_id", "") or ""),
        ),
        reverse=True,
    )[: max(1, min(int(recent_limit), 500))]
    return {
        "version": M314_CANDIDATE_ROUNDTRIP_VERSION,
        "scope": M314_CANDIDATE_ROUNDTRIP_SCOPE,
        "gate_armed": M314_CANDIDATE_ROUNDTRIP_GATE_ARMED,
        "strict_forward_only": True,
        "backfill": False,
        "entry_count": len(entries),
        "open_position_count": open_position_count,
        "closed_trade_count": len(closed),
        "net_pnl_lamports": net_pnl,
        "net_pnl_sol": net_pnl / 1_000_000_000,
        "gross_profit_lamports": gross_profit,
        "gross_loss_lamports": gross_loss,
        "profit_factor": round(profit_factor, 8),
        "maximum_drawdown_lamports": max_drawdown_lamports,
        "maximum_drawdown_percent": round(max_drawdown_percent, 8),
        "maximum_realized_equity_drawdown_percent": round(
            realized_equity_drawdown_percent, 8
        ),
        "best_trade_lamports": best_trade,
        "net_without_best_trade_lamports": net_without_best,
        "technical_exit_failure_count": len(unique_failures),
        "economic_gate": economic_gate,
        "economic_observation_pass": economics_pass,
        "m307_authorized": False,
        "recent_positions": [
            {
                "event_id": str(getattr(row, "event_id", "") or ""),
                "wallet": state.get("wallet_address"),
                "token_mint": state.get("token_mint"),
                "entry_signature": state.get("entry_signature"),
                "status": state.get("status"),
                "opened_at": state.get("opened_at"),
                "closed_at": state.get("closed_at"),
                "pnl_lamports": state.get("pnl_lamports"),
                "return_percent": state.get("return_percent"),
            }
            for row, state in recent
        ],
        "safety": {
            "observation_only": True,
            "m300_changed": False,
            "m298_changed": False,
            "m307_changed": False,
            "live_execution": False,
            "paper_execution": False,
            "signer_access": False,
            "automatic_promotion": False,
        },
    }


def get_gen4_candidate_roundtrip_shadow_status(
    db: Session,
    *,
    recent_limit: int = 100,
) -> dict[str, Any]:
    rows = list(
        db.scalars(
            select(CanonicalParserGen4FastpathShadowEvent)
            .order_by(
                CanonicalParserGen4FastpathShadowEvent.fast_received_at,
                CanonicalParserGen4FastpathShadowEvent.id,
            )
        )
    )
    candidate_rows = [row for row in rows if _is_candidate_event(row)]
    aggregate = _candidate_roundtrip_metrics_from_events(
        candidate_rows,
        recent_limit=recent_limit,
    )
    grouped: dict[str, list[Any]] = {}
    for row in candidate_rows:
        state = _candidate_roundtrip_state(row)
        if state is None:
            continue
        wallet = str(state.get("wallet_address") or "").strip()
        if not wallet:
            continue
        grouped.setdefault(wallet, []).append(row)

    wallet_summaries: dict[str, Any] = {}
    for wallet, wallet_rows in sorted(grouped.items()):
        metrics = _candidate_roundtrip_metrics_from_events(
            wallet_rows,
            recent_limit=min(max(1, int(recent_limit)), 20),
        )
        wallet_summaries[wallet] = {
            key: value
            for key, value in metrics.items()
            if key != "recent_positions"
        }

    aggregate["wallets"] = wallet_summaries
    aggregate["m316_copyable_alpha_diagnostics"] = (
        build_m316_candidate_alpha_diagnostics(
            events=candidate_rows,
            evaluated_at=_utc_now(),
        )
    )
    aggregate["safety"] = {
        **dict(aggregate.get("safety") or {}),
        "m316_diagnostics_observation_only": True,
        "m316_shadow_filter_armed": False,
    }
    return aggregate


def _candidate_entry_quote(
    *,
    input_mint: str,
    output_mint: str,
    amount_raw: int,
    slippage_bps: int,
    client: JupiterSwapClient,
) -> Any:
    """Candidate BUY build-priority quote; test doubles keep legacy fallback."""
    build_priority = getattr(client, "get_build_priority_unsigned", None)
    if not callable(build_priority):
        return _quote(
            input_mint=input_mint,
            output_mint=output_mint,
            amount_raw=amount_raw,
            slippage_bps=slippage_bps,
            client=client,
        )

    requested = _utc_now()
    taker = str(
        getattr(
            settings,
            "CANONICAL_PARSER_GEN4_COPYABILITY_QUOTE_TAKER",
            "",
        )
        or ""
    ).strip() or None
    if not taker:
        raise JupiterSwapError(
            "CANONICAL_PARSER_GEN4_COPYABILITY_QUOTE_TAKER mancante.",
            code="GEN4_COPYABILITY_QUOTE_TAKER_MISSING",
            status_code=503,
        )
    result = build_priority(
        input_mint=input_mint,
        output_mint=output_mint,
        amount_raw=int(amount_raw),
        taker=taker,
        slippage_bps=int(slippage_bps),
        mode="fast",
    )
    received = _utc_now()
    latency = max(
        0,
        int((received - requested).total_seconds() * 1000),
    )
    sanitized = dict(getattr(result, "raw", None) or {})
    sanitized.update(
        {
            "request_id": result.request_id,
            "in_amount": result.in_amount,
            "out_amount": result.out_amount,
            "slippage_bps": result.slippage_bps,
            "router": result.router,
            "price_impact_percent": result.price_impact_percent,
            "transaction_built": bool(result.transaction),
            "candidate_build_priority": True,
            "order_diagnostic_available": False,
        }
    )
    return SimpleNamespace(
        requested_at=requested,
        received_at=received,
        latency_ms=latency,
        result=result,
        sanitized=sanitized,
    )


def record_fastpath_candidate_notification(
    db: Session,
    *,
    message: dict[str, Any],
    jupiter_client: JupiterSwapClient,
    received_at: datetime | None = None,
    provider_slot_clock: dict[str, Any] | None = None,
) -> dict[str, Any]:
    observed = _aware(received_at) or _utc_now()
    payload = normalize_helius_transaction_notification(message)
    signature = str(payload["signature"])
    wallets = configured_fastpath_candidate_wallets()
    if not wallets:
        return {"status": "IGNORED_NO_CANDIDATE_WALLETS", "signature": signature}

    promoted_position: CanonicalParserGen4PromotedSelectivePosition | None = None
    promoted_sell_context: tuple[
        Any, CanonicalParserGen4PromotedSelectiveActivation
    ] | None = None

    candidate_roundtrip_sell_context: tuple[Any, dict[str, Any]] | None = None
    candidate_order_diagnostic_request: dict[str, Any] | None = None

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
        _m319_set_candidate_observation(
            event,
            _new_m319_candidate_observation(
                event=event,
                signal=signal,
                received_at=observed,
                parsed_at=parsed_at,
                provider_slot_clock=provider_slot_clock,
            ),
        )
        promoted_activation = get_promoted_activation_for_event(
            db,
            wallet=str(signal.wallet_address),
            event_received_at=observed,
            side=str(signal.side),
        )
        if signal.side == "BUY":
            policy = dict(event.policy_snapshot or {})
            pump_shadow = quote_pump_buy_exact_sol_in_shadow(
                payload,
                wallet_address=signal.wallet_address,
                token_mint=signal.token_mint,
                token_decimals=signal.token_decimals,
                wallet_effective_price_sol=signal.wallet_effective_price_sol,
                simulated_input_lamports=int(policy["simulated_input_lamports"]),
                slippage_bps=int(policy["slippage_bps"]),
            )
            event.evidence = {
                **dict(event.evidence or {}),
                "pump_shadow": pump_shadow,
            }
            try:
                quote = _candidate_entry_quote(
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
                _m319_update_buy_quote(
                    event,
                    quote=quote,
                    deterioration_bps=deterioration,
                    price_impact_bps=impact_bps,
                    rejection_reason=reason,
                )
                if bool(
                    dict(getattr(quote, "sanitized", None) or {}).get(
                        "candidate_build_priority"
                    )
                ):
                    build_received_at = (
                        _aware(quote.received_at) or _utc_now()
                    )
                    candidate_order_diagnostic_request = {
                        "version": M320_CANDIDATE_ORDER_DIAGNOSTIC_VERSION,
                        "event_id": str(event.event_id),
                        "signature": str(signature),
                        "wallet_address": str(signal.wallet_address),
                        "input_mint": SOL_MINT,
                        "output_mint": str(signal.token_mint),
                        "amount_raw": int(policy["simulated_input_lamports"]),
                        "slippage_bps": int(policy["slippage_bps"]),
                        "build_request_id": str(quote.result.request_id),
                        "build_out_amount": int(quote.result.out_amount),
                        "build_received_at_utc": build_received_at.isoformat(),
                    }
                    event.evidence = {
                        **dict(event.evidence or {}),
                        M320_CANDIDATE_ORDER_DIAGNOSTIC_EVIDENCE_KEY: {
                            "version": M320_CANDIDATE_ORDER_DIAGNOSTIC_VERSION,
                            "state": "PENDING_POST_COMMIT_LOW_PRIORITY",
                            "critical_path": False,
                            "affects_entry_decision": False,
                            "covers_rejected_buys": True,
                            "build_request_id": str(quote.result.request_id),
                            "build_out_amount": int(quote.result.out_amount),
                            "build_received_at_utc": build_received_at.isoformat(),
                            "event_id": str(event.event_id),
                            "signature": str(signature),
                            "wallet_address": str(signal.wallet_address),
                            "input_mint": SOL_MINT,
                            "output_mint": str(signal.token_mint),
                            "amount_raw": int(policy["simulated_input_lamports"]),
                            "slippage_bps": int(policy["slippage_bps"]),
                            "order_called_before_build_decision": False,
                            "live_execution": False,
                            "signer_access": False,
                        },
                    }
                if reason is None:
                    conservative_out = _conservative_out_amount(
                        quote.result, int(policy["slippage_bps"])
                    )
                    event.evidence = {
                        **dict(event.evidence or {}),
                        M314_CANDIDATE_ROUNDTRIP_EVIDENCE_KEY: _new_candidate_roundtrip_state(
                            event=event,
                            signal=signal,
                            policy=policy,
                            quote=quote,
                            conservative_out=int(conservative_out),
                            deterioration_bps=deterioration,
                            price_impact_bps=impact_bps,
                        ),
                    }
                if promoted_activation is not None:
                    lifecycle = {
                        "version": PROMOTED_SELECTIVE_POSITION_VERSION,
                        "scope": PROMOTED_SELECTIVE_SCOPE,
                        "activation_id": str(promoted_activation.activation_id),
                        "activation_status": str(promoted_activation.status),
                        "post_activation_only": True,
                        "prepromotion_backfill": False,
                        "entry_eligible": False,
                        "position_id": None,
                        "reason": reason,
                        "policy_violation": False,
                        "live_execution": False,
                        "paper_execution": False,
                        "signer_access": False,
                    }
                    if reason is None:
                        if _promoted_policy_matches_candidate_event(
                            event, promoted_activation
                        ):
                            conservative_out = _conservative_out_amount(
                                quote.result,
                                int(
                                    dict(promoted_activation.policy_snapshot or {})[
                                        "slippage_bps"
                                    ]
                                ),
                            )
                            promoted_position = _new_promoted_selective_position(
                                event=event,
                                signal=signal,
                                activation=promoted_activation,
                                quote=quote,
                                conservative_out=conservative_out,
                                deterioration_bps=deterioration,
                                price_impact_bps=impact_bps,
                            )
                            lifecycle.update(
                                {
                                    "entry_eligible": True,
                                    "position_id": promoted_position.position_id,
                                    "reason": None,
                                }
                            )
                        else:
                            lifecycle.update(
                                {
                                    "reason": "ACTIVATION_POLICY_DRIFT",
                                    "policy_violation": True,
                                }
                            )
                    event.evidence = {
                        **dict(event.evidence or {}),
                        "promoted_selective_lifecycle": lifecycle,
                    }
            except JupiterSwapError as exc:
                _record_jupiter_entry_error(event, exc)
        else:
            event.fast_provisional_rejection_reason = "NOT_A_BUY_SIGNAL"
            if signal.side == "SELL":
                policy = dict(event.policy_snapshot or {})
                event.evidence = {
                    **dict(event.evidence or {}),
                    "m314_candidate_roundtrip_sell": {
                        "version": M314_CANDIDATE_ROUNDTRIP_VERSION,
                        "scope": M314_CANDIDATE_ROUNDTRIP_SCOPE,
                        "sell_fraction": signal.sell_fraction,
                        "strict_forward_only": True,
                        "backfill": False,
                        "quote_attempted": False,
                        "live_execution": False,
                        "paper_execution": False,
                        "signer_access": False,
                    },
                }
                candidate_roundtrip_sell_context = (signal, policy)
            if signal.side == "SELL" and promoted_activation is not None:
                promoted_sell_context = (signal, promoted_activation)
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
            if candidate_roundtrip_sell_context is not None:
                candidate_signal, candidate_policy = candidate_roundtrip_sell_context
                m314_sell = _apply_candidate_roundtrip_sell_shadow(
                    db,
                    event=event,
                    signal=candidate_signal,
                    policy=candidate_policy,
                    jupiter_client=jupiter_client,
                )
                sell_evidence = dict(
                    dict(event.evidence or {}).get("m314_candidate_roundtrip_sell") or {}
                )
                event.evidence = {
                    **dict(event.evidence or {}),
                    "m314_candidate_roundtrip_sell": {
                        **sell_evidence,
                        **m314_sell,
                    },
                }
                _m319_update_sell_shadow(
                    event,
                    dict(event.evidence or {}).get("m314_candidate_roundtrip_sell") or {},
                )
                db.flush()
            if promoted_position is not None:
                db.add(promoted_position)
            if promoted_sell_context is not None:
                promoted_signal, promoted_activation = promoted_sell_context
                promoted_exit = _apply_promoted_selective_sell_shadow(
                    db,
                    event=event,
                    signal=promoted_signal,
                    activation=promoted_activation,
                    jupiter_client=jupiter_client,
                )
                event.evidence = {
                    **dict(event.evidence or {}),
                    "promoted_selective_lifecycle": promoted_exit,
                }
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

    promoted_evidence = dict(
        dict(event.evidence or {}).get("promoted_selective_lifecycle") or {}
    )
    return {
        "status": "RECORDED_CANDIDATE",
        "signature": signature,
        "wallet": event.wallet_address,
        "side": event.side,
        "provisional_copyable": bool(event.fast_provisional_copyable),
        "rejection": event.fast_provisional_rejection_reason,
        "quote_error": event.quote_error_code,
        "promoted_selective_lifecycle": promoted_evidence,
        "promoted_position_created": promoted_position is not None,
        "promoted_exit_applied": bool(promoted_evidence.get("exit_applied")),
        "deferred_order_diagnostic": (
            dict(candidate_order_diagnostic_request)
            if isinstance(candidate_order_diagnostic_request, dict)
            else None
        ),
    }


def record_candidate_order_diagnostic(
    db: Session,
    *,
    request: dict[str, Any],
    jupiter_client: JupiterSwapClient,
) -> dict[str, Any]:
    """Persist low-priority /order evidence after the candidate BUY commit."""
    version = str(request.get("version") or "")
    if version != M320_CANDIDATE_ORDER_DIAGNOSTIC_VERSION:
        return {
            "status": "IGNORED_DIAGNOSTIC_VERSION",
            "version": version,
        }

    event_id = str(request.get("event_id") or "").strip()
    signature = str(request.get("signature") or "").strip()
    wallet = str(request.get("wallet_address") or "").strip()
    if not event_id or not signature or not wallet:
        return {"status": "IGNORED_DIAGNOSTIC_IDENTITY"}

    event = db.scalar(
        select(CanonicalParserGen4FastpathShadowEvent).where(
            CanonicalParserGen4FastpathShadowEvent.event_id == event_id,
        )
    )
    if event is None or not _is_candidate_event(event):
        return {"status": "DIAGNOSTIC_EVENT_NOT_FOUND"}
    if (
        str(event.signature) != signature
        or str(event.wallet_address) != wallet
        or str(event.side or "") != "BUY"
    ):
        return {"status": "DIAGNOSTIC_EVENT_IDENTITY_MISMATCH"}

    evidence = dict(event.evidence or {})
    current = dict(
        evidence.get(M320_CANDIDATE_ORDER_DIAGNOSTIC_EVIDENCE_KEY) or {}
    )
    if str(current.get("version") or "") != M320_CANDIDATE_ORDER_DIAGNOSTIC_VERSION:
        return {"status": "DIAGNOSTIC_PENDING_EVIDENCE_MISSING"}
    if str(current.get("state") or "") == "COMPLETE":
        return {"status": "DIAGNOSTIC_ALREADY_COMPLETE"}

    build_out = int(request.get("build_out_amount") or 0)
    build_received = None
    raw_build_received = request.get("build_received_at_utc")
    if raw_build_received:
        try:
            build_received = datetime.fromisoformat(
                str(raw_build_received).replace("Z", "+00:00")
            )
            build_received = _aware(build_received)
        except ValueError:
            build_received = None

    diagnostic_requested = _utc_now()
    delay_from_build_ms = (
        max(
            0,
            int(
                (
                    diagnostic_requested - build_received
                ).total_seconds()
                * 1000
            ),
        )
        if build_received is not None
        else None
    )

    order_diagnostic = getattr(
        jupiter_client,
        "get_order_diagnostic",
        None,
    )
    if not callable(order_diagnostic):
        current.update(
            {
                "state": "FAILED_UNSUPPORTED_CLIENT",
                "completed_at_utc": _utc_now().isoformat(),
                "critical_path": False,
                "affects_entry_decision": False,
            }
        )
        evidence[M320_CANDIDATE_ORDER_DIAGNOSTIC_EVIDENCE_KEY] = current
        event.evidence = evidence
        db.flush()
        return {"status": "DIAGNOSTIC_UNSUPPORTED_CLIENT"}

    try:
        result = order_diagnostic(
            input_mint=str(request.get("input_mint") or ""),
            output_mint=str(request.get("output_mint") or ""),
            amount_raw=int(request.get("amount_raw") or 0),
            slippage_bps=int(request.get("slippage_bps") or 0),
        )
    except JupiterSwapError as exc:
        current.update(
            {
                "state": "FAILED",
                "completed_at_utc": _utc_now().isoformat(),
                "diagnostic_delay_from_build_ms": delay_from_build_ms,
                "jupiter_error": _jupiter_error_snapshot(exc),
                "critical_path": False,
                "affects_entry_decision": False,
                "live_execution": False,
                "signer_access": False,
            }
        )
        evidence[M320_CANDIDATE_ORDER_DIAGNOSTIC_EVIDENCE_KEY] = current
        event.evidence = evidence
        db.flush()
        return {
            "status": "DIAGNOSTIC_FAILED",
            "code": str(exc.code),
        }

    order_out = int(result.get("outAmount") or 0)
    if build_out <= 0 or order_out <= 0:
        current.update(
            {
                "state": "FAILED_INVALID_AMOUNT",
                "completed_at_utc": _utc_now().isoformat(),
                "diagnostic_delay_from_build_ms": delay_from_build_ms,
                "critical_path": False,
                "affects_entry_decision": False,
            }
        )
        evidence[M320_CANDIDATE_ORDER_DIAGNOSTIC_EVIDENCE_KEY] = current
        event.evidence = evidence
        db.flush()
        return {"status": "DIAGNOSTIC_INVALID_AMOUNT"}

    build_vs_order_out_bps = (
        (float(build_out) / float(order_out)) - 1.0
    ) * 10_000.0
    completed = _utc_now()

    current.update(
        {
            "state": "COMPLETE",
            "completed_at_utc": completed.isoformat(),
            "diagnostic_delay_from_build_ms": delay_from_build_ms,
            "order_request_id": str(result.get("requestId") or ""),
            "order_in_amount": int(result.get("inAmount") or 0),
            "order_out_amount": order_out,
            "order_router": result.get("router"),
            "order_price_impact": result.get("priceImpact"),
            "order_component_timing": dict(
                result.get("componentTiming") or {}
            ),
            "build_vs_order_out_bps": round(
                build_vs_order_out_bps,
                4,
            ),
            "critical_path": False,
            "affects_entry_decision": False,
            "order_called_before_build_decision": False,
            "live_execution": False,
            "signer_access": False,
        }
    )
    evidence[M320_CANDIDATE_ORDER_DIAGNOSTIC_EVIDENCE_KEY] = current
    event.evidence = evidence
    db.flush()
    return {
        "status": "DIAGNOSTIC_COMPLETE",
        "build_vs_order_out_bps": float(build_vs_order_out_bps),
    }


def load_pending_candidate_order_diagnostics(
    db: Session,
    *,
    limit: int = 256,
) -> list[dict[str, Any]]:
    """Recover persisted pending diagnostics after a process restart."""
    bounded = max(1, min(int(limit), 256))
    scan_limit = min(5000, max(512, bounded * 12))
    rows = list(
        db.scalars(
            select(CanonicalParserGen4FastpathShadowEvent)
            .where(CanonicalParserGen4FastpathShadowEvent.side == "BUY")
            .order_by(
                CanonicalParserGen4FastpathShadowEvent.fast_received_at.desc()
            )
            .limit(scan_limit)
        )
    )
    pending: list[dict[str, Any]] = []
    for event in rows:
        if not _is_candidate_event(event):
            continue
        evidence = dict(event.evidence or {})
        item = evidence.get(M320_CANDIDATE_ORDER_DIAGNOSTIC_EVIDENCE_KEY)
        if not isinstance(item, dict):
            continue
        if str(item.get("version") or "") != M320_CANDIDATE_ORDER_DIAGNOSTIC_VERSION:
            continue
        if str(item.get("state") or "") != "PENDING_POST_COMMIT_LOW_PRIORITY":
            continue
        request = {
            "version": M320_CANDIDATE_ORDER_DIAGNOSTIC_VERSION,
            "event_id": str(item.get("event_id") or event.event_id),
            "signature": str(item.get("signature") or event.signature),
            "wallet_address": str(
                item.get("wallet_address") or event.wallet_address
            ),
            "input_mint": str(item.get("input_mint") or ""),
            "output_mint": str(item.get("output_mint") or event.token_mint or ""),
            "amount_raw": int(item.get("amount_raw") or 0),
            "slippage_bps": int(item.get("slippage_bps") or 0),
            "build_request_id": str(item.get("build_request_id") or ""),
            "build_out_amount": int(item.get("build_out_amount") or 0),
            "build_received_at_utc": item.get("build_received_at_utc"),
        }
        if (
            request["event_id"]
            and request["signature"]
            and request["wallet_address"]
            and request["input_mint"]
            and request["output_mint"]
            and request["amount_raw"] > 0
            and request["build_out_amount"] > 0
        ):
            pending.append(request)
        if len(pending) >= bounded:
            break
    pending.reverse()
    return pending


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
    pump_shadow_rows = [
        dict(dict(row.evidence or {}).get("pump_shadow") or {})
        for row in buys
        if isinstance(dict(row.evidence or {}).get("pump_shadow"), dict)
    ]
    pump_shadow_available = [
        value for value in pump_shadow_rows if value.get("available") is True
    ]
    pump_shadow_failures = Counter(
        str(value.get("reason"))
        for value in pump_shadow_rows
        if value.get("available") is not True and value.get("reason")
    )
    pump_shadow_latencies = [
        float(value["quote_latency_ms"])
        for value in pump_shadow_available
        if value.get("quote_latency_ms") is not None
    ]
    pump_shadow_deterioration = [
        float(value["price_deterioration_bps"])
        for value in pump_shadow_available
        if value.get("price_deterioration_bps") is not None
    ]
    pump_shadow_impact = [
        float(value["diagnostic_curve_impact_bps"])
        for value in pump_shadow_available
        if value.get("diagnostic_curve_impact_bps") is not None
    ]
    pump_shadow_pam_pass = [
        value for value in pump_shadow_available if value.get("pam_pass") is True
    ]
    pump_shadow_diagnostic_pass = [
        value
        for value in pump_shadow_available
        if value.get("diagnostic_quote_pass") is True
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
        "pump_shadow_ab": {
            "version": "m132-pump-event-local-quote-shadow/1",
            "attempted_buy_count": len(pump_shadow_rows),
            "available_quote_count": len(pump_shadow_available),
            "availability_percent_of_buys": round(
                (
                    100.0 * len(pump_shadow_available) / len(buys)
                    if buys
                    else 0.0
                ),
                8,
            ),
            "pam_pass_count": len(pump_shadow_pam_pass),
            "pam_pass_percent_of_available": round(
                (
                    100.0
                    * len(pump_shadow_pam_pass)
                    / len(pump_shadow_available)
                    if pump_shadow_available
                    else 0.0
                ),
                8,
            ),
            "diagnostic_quote_pass_count": len(pump_shadow_diagnostic_pass),
            "diagnostic_quote_pass_percent_of_available": round(
                (
                    100.0
                    * len(pump_shadow_diagnostic_pass)
                    / len(pump_shadow_available)
                    if pump_shadow_available
                    else 0.0
                ),
                8,
            ),
            "failure_breakdown": dict(sorted(pump_shadow_failures.items())),
            "quote_latency_ms": {
                "p50": _percentile(pump_shadow_latencies, 0.50),
                "p95": _percentile(pump_shadow_latencies, 0.95),
            },
            "price_deterioration_bps": {
                "p50": _percentile(pump_shadow_deterioration, 0.50),
                "p95": _percentile(pump_shadow_deterioration, 0.95),
                "max": (
                    max(pump_shadow_deterioration)
                    if pump_shadow_deterioration
                    else None
                ),
            },
            "diagnostic_curve_impact_bps": {
                "p95": _percentile(pump_shadow_impact, 0.95),
                "max": max(pump_shadow_impact) if pump_shadow_impact else None,
            },
            "provider_api_calls": 0,
            "rpc_reads": 0,
            "transaction_built": False,
            "canonical_acceptance_mutated": False,
            "m75_forward_pass": False,
            "live_execution": False,
            "signer_access": False,
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
                "pump_shadow": (
                    dict(row.evidence or {}).get("pump_shadow")
                    if isinstance(dict(row.evidence or {}).get("pump_shadow"), dict)
                    else None
                ),
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



def get_gen4_fastpath_forward_wallet_status(
    db: Session,
    *,
    wallet_address: str,
    anchor_utc: datetime,
    scope: str = "CANDIDATE",
    recent_limit: int = 50,
) -> dict[str, Any]:
    wallet = str(wallet_address or "").strip()
    if not wallet:
        raise ValueError("FASTPATH_FORWARD_WALLET_REQUIRED")

    anchor = _aware(anchor_utc)
    if anchor is None:
        raise ValueError("FASTPATH_FORWARD_ANCHOR_REQUIRED")

    normalized_scope = str(scope or "CANDIDATE").strip().upper()
    if normalized_scope not in {"CANDIDATE", "OFFICIAL"}:
        raise ValueError("FASTPATH_FORWARD_SCOPE_INVALID")

    queried = list(
        db.scalars(
            select(CanonicalParserGen4FastpathShadowEvent).where(
                CanonicalParserGen4FastpathShadowEvent.wallet_address == wallet,
                CanonicalParserGen4FastpathShadowEvent.fast_received_at >= anchor,
            )
        )
    )
    rows = [
        row
        for row in queried
        if str(row.wallet_address) == wallet
        and (_aware(row.fast_received_at) or anchor) >= anchor
        and (
            _is_candidate_event(row)
            if normalized_scope == "CANDIDATE"
            else not _is_candidate_event(row)
        )
    ]
    rows.sort(key=lambda row: row.fast_received_at)

    buys = [row for row in rows if row.side == "BUY"]
    sells = [row for row in rows if row.side == "SELL"]
    accepted = [row for row in buys if bool(row.fast_provisional_copyable)]
    rejected = [row for row in buys if not bool(row.fast_provisional_copyable)]
    pam_rejected = [
        row
        for row in buys
        if row.fast_provisional_rejection_reason == "PRICE_ALREADY_MOVED"
    ]
    parse_errors = [row for row in rows if row.parse_error_code]
    quote_errors = [row for row in buys if row.quote_error_code]

    latency_values = []
    deterioration_values = []
    impact_values = []
    for row in buys:
        if row.fast_end_to_quote_ms is not None:
            latency_values.append(float(row.fast_end_to_quote_ms))
        elif row.fast_quote_latency_ms is not None:
            latency_values.append(
                float((row.fast_prequote_ms or 0) + row.fast_quote_latency_ms)
            )
        if row.fast_price_deterioration_bps is not None:
            deterioration_values.append(float(row.fast_price_deterioration_bps))
        if row.fast_price_impact_bps is not None:
            impact_values.append(float(row.fast_price_impact_bps))

    rejection_breakdown = Counter(
        str(row.fast_provisional_rejection_reason or "UNSPECIFIED")
        for row in rejected
    )

    buy_count = len(buys)
    acceptance_rate = (
        round(100.0 * len(accepted) / buy_count, 8) if buy_count else None
    )
    reject_rate = (
        round(100.0 * len(rejected) / buy_count, 8) if buy_count else None
    )
    pam_rate = (
        round(100.0 * len(pam_rejected) / buy_count, 8) if buy_count else None
    )
    attempts_met = buy_count >= 20
    reject_rate_pass = bool(
        attempts_met and reject_rate is not None and reject_rate <= 20.0
    )

    limit = max(1, min(int(recent_limit), 500))
    recent = list(reversed(rows[-limit:]))

    result = {
        "version": "m169-fastpath-persistent-forward-wallet-status/1",
        "persistent_db_evidence": True,
        "window_limited": False,
        "wallet": wallet,
        "scope": normalized_scope,
        "anchor_utc": anchor,
        "event_count": len(rows),
        "buy_count": buy_count,
        "sell_count": len(sells),
        "accepted_buy_count": len(accepted),
        "rejected_buy_count": len(rejected),
        "entry_acceptance_rate_percent": acceptance_rate,
        "entry_reject_rate_percent": reject_rate,
        "pam_rejection_count": len(pam_rejected),
        "pam_rejection_rate_percent": pam_rate,
        "parse_error_count": len(parse_errors),
        "quote_error_count": len(quote_errors),
        "rejection_breakdown": dict(sorted(rejection_breakdown.items())),
        "fast_received_to_quote_ms": {
            "p50": _percentile(latency_values, 0.50),
            "p95": _percentile(latency_values, 0.95),
        },
        "price_deterioration_bps": {
            "p50": _percentile(deterioration_values, 0.50),
            "p95": _percentile(deterioration_values, 0.95),
            "max": max(deterioration_values) if deterioration_values else None,
        },
        "price_impact_bps": {
            "p50": _percentile(impact_values, 0.50),
            "p95": _percentile(impact_values, 0.95),
            "max": max(impact_values) if impact_values else None,
        },
        "first_event_at": rows[0].fast_received_at if rows else None,
        "last_event_at": rows[-1].fast_received_at if rows else None,
        "entry_gate": {
            "minimum_attempts": 20,
            "attempts_met": attempts_met,
            "maximum_reject_rate_percent": 20.0,
            "reject_rate_pass": reject_rate_pass,
            "price_already_moved_limit_bps": 1_000,
            "price_already_moved_unchanged": True,
        },
        "m75_forward_pass": False,
        "m75_forward_pass_reason": (
            "PERSISTENT_FORWARD_ENTRY_ONLY_NO_24H_CLOSED_WEBHOOK_PROOF"
        ),
        "recent": [
            {
                "signature": row.signature,
                "wallet": row.wallet_address,
                "side": row.side,
                "fast_received_at": row.fast_received_at,
                "fast_prequote_ms": row.fast_prequote_ms,
                "fast_quote_latency_ms": row.fast_quote_latency_ms,
                "fast_end_to_quote_ms": row.fast_end_to_quote_ms,
                "fast_price_deterioration_bps": row.fast_price_deterioration_bps,
                "fast_price_impact_bps": row.fast_price_impact_bps,
                "fast_transaction_built": row.fast_transaction_built,
                "fast_provisional_copyable": row.fast_provisional_copyable,
                "fast_rejection": row.fast_provisional_rejection_reason,
                "parse_error": row.parse_error_code,
                "quote_error": row.quote_error_code,
            }
            for row in recent
        ],
        "safety": {
            "provider_history_calls": 0,
            "helius_credits": 0,
            "birdeye_cu": 0,
            "campaign_created": False,
            "campaign_metrics_mutated": False,
            "positions_created": 0,
            "live_execution": False,
            "signer_access": False,
            "submitted_transactions": 0,
            "paper_orders": 0,
        },
    }
    if normalized_scope == "OFFICIAL":
        result["m75_native_bridge"] = load_fastpath_native_m75_bridge(
            db,
            wallet=wallet,
            events=rows,
            anchor_utc=anchor,
            terminal_at=_utc_now(),
        )
    else:
        result["m75_native_bridge"] = {
            "scope": "M282_FASTPATH_NATIVE_M75_EVIDENCE_BRIDGE_DISARMED",
            "version": "m282-fastpath-native-m75-evidence-bridge/1",
            "state": "NOT_APPLICABLE_CANDIDATE_SCOPE",
            "formal_m75_claimed": False,
            "formal_m75_pass": False,
            "micro_live_execution_authorized": False,
        }
    return result

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



def reconcile_m319_candidate_edge_instrumentation(
    db: Session,
    *,
    limit: int = 200,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Reconcile only prospective M319 candidate rows with existing raw webhook receipts.

    Historical candidate rows have no M319 marker and are intentionally ignored.
    No provider request is made here; this reads already-persisted webhook receipts.
    """
    observed = _aware(now) or _utc_now()
    window_start = observed - timedelta(minutes=M319_COPYABLE_EDGE_RECONCILE_WINDOW_MINUTES)
    scan_limit = max(1, min(max(int(limit) * 5, int(limit)), 1000))
    rows = list(
        db.scalars(
            select(CanonicalParserGen4FastpathShadowEvent)
            .where(
                CanonicalParserGen4FastpathShadowEvent.webhook_reconciled_at.is_(None),
                CanonicalParserGen4FastpathShadowEvent.fast_received_at >= window_start,
            )
            .order_by(
                CanonicalParserGen4FastpathShadowEvent.fast_received_at,
                CanonicalParserGen4FastpathShadowEvent.id,
            )
            .limit(scan_limit)
        )
    )
    checked = 0
    reconciled = 0
    for event in rows:
        if not _is_candidate_event(event):
            continue
        evidence = dict(event.evidence or {})
        current = evidence.get(M319_COPYABLE_EDGE_EVIDENCE_KEY)
        if not isinstance(current, dict):
            continue
        if str(current.get("version") or "") != M319_COPYABLE_EDGE_VERSION:
            continue
        checked += 1
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

        webhook_received = _aware(receipt.received_at)
        block_time = _aware(receipt.block_time)
        event.webhook_received_at = webhook_received
        event.webhook_block_time = block_time
        event.webhook_reconciled_at = observed
        event.fast_lead_vs_webhook_ms = (
            _m319_elapsed_ms(webhook_received, _aware(event.fast_received_at))
            if webhook_received is not None
            else None
        )
        if event.fast_quote_received_at is not None and block_time is not None:
            event.fast_end_to_quote_ms = _m319_elapsed_ms(
                _aware(event.fast_quote_received_at),
                block_time,
            )

        observation = dict(current)
        if block_time is not None:
            observation["source_block_time_utc"] = block_time.isoformat()
            observation["source_block_time_origin"] = "RAW_WEBHOOK_RECEIPT"
            observation["chain_to_receive_ms"] = _m319_elapsed_ms(
                _aware(event.fast_received_at),
                block_time,
            )
            observation["chain_to_parse_ms"] = _m319_elapsed_ms(
                _aware(event.fast_parse_completed_at),
                block_time,
            )
            follower_entry = observation.get("follower_entry")
            if isinstance(follower_entry, dict):
                updated_entry = dict(follower_entry)
                updated_entry["chain_to_quote_received_ms"] = _m319_elapsed_ms(
                    _aware(event.fast_quote_received_at),
                    block_time,
                )
                observation["follower_entry"] = updated_entry
        observation["reconciliation"] = {
            "attempted": True,
            "matched_raw_webhook": True,
            "reconciled_at_utc": observed.isoformat(),
            "raw_webhook_received_at_utc": (
                webhook_received.isoformat() if webhook_received is not None else None
            ),
            "raw_webhook_block_time_utc": (
                block_time.isoformat() if block_time is not None else None
            ),
            "fast_lead_vs_webhook_ms": event.fast_lead_vs_webhook_ms,
        }
        evidence[M319_COPYABLE_EDGE_EVIDENCE_KEY] = observation
        event.evidence = evidence
        reconciled += 1

    return {
        "version": M319_COPYABLE_EDGE_VERSION,
        "scope": M319_COPYABLE_EDGE_SCOPE,
        "window_minutes": M319_COPYABLE_EDGE_RECONCILE_WINDOW_MINUTES,
        "checked_m319_candidate_rows": checked,
        "reconciled_m319_candidate_rows": reconciled,
        "provider_calls": 0,
        "backfill": False,
        "automatic_filtering": False,
        "automatic_promotion": False,
        "live_execution": False,
    }


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
        "selective_position_shadow": _selective_position_status(
            db, official_events=all_rows, recent_limit=limit
        ),
        "m316_copyable_alpha_diagnostics": build_m316_candidate_alpha_diagnostics(
            events=candidate_rows,
            evaluated_at=_utc_now(),
        ),
        "safety": {
            "live_execution": False,
            "signer_access": False,
            "submitted_transactions": 0,
            "paper_orders": 0,
            "m114_m117_metrics_mutated": False,
            "m117d_official_counters_include_candidate_rows": False,
            "m138_selective_positions_mutate_m114_m117_metrics": False,
            "m316_diagnostics_observation_only": True,
            "m316_shadow_filter_armed": False,
        },
    }
