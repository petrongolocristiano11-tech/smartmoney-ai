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
    CanonicalParserGen4FastpathSelectivePosition,
    CanonicalParserGen4FastpathShadowEvent,
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
from backend.app.services.jupiter_swap_client import JupiterSwapClient
from backend.app.services.live_trading_errors import JupiterSwapError
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
FASTPATH_SELECTIVE_MIN_CLOSED = 10
FASTPATH_SELECTIVE_MIN_PROFIT_FACTOR = 1.30
FASTPATH_SELECTIVE_MAX_DRAWDOWN_PERCENT = 15.0


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
                    event.quote_error_code = str(exc.code)
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
        "selective_position_shadow": _selective_position_status(
            db, official_events=all_rows, recent_limit=limit
        ),
        "safety": {
            "live_execution": False,
            "signer_access": False,
            "submitted_transactions": 0,
            "paper_orders": 0,
            "m114_m117_metrics_mutated": False,
            "m117d_official_counters_include_candidate_rows": False,
            "m138_selective_positions_mutate_m114_m117_metrics": False,
        },
    }
