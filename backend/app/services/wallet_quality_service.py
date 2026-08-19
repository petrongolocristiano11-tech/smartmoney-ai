from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Iterable

from sqlalchemy.orm import Session

from backend.app.models.trade import Trade
from backend.app.services.wallet_activity_service import (
    ACTIVITY_CLASS_ACTIVE,
    ACTIVITY_CLASS_HYPERACTIVE,
    ACTIVITY_CLASS_INACTIVE,
    ACTIVITY_CLASS_LOW,
    clamp,
    ensure_aware,
    safe_float,
)


QUALITY_CLASS_COPYABLE = "COPIABILE"
QUALITY_CLASS_OBSERVATION = "OSSERVAZIONE"
QUALITY_CLASS_SUSPICIOUS = "SOSPETTO"
QUALITY_CLASS_NOT_COPYABLE = "NON_COPIABILE"
QUALITY_CLASS_NOT_ANALYZED = "NON_ANALIZZATO"

QUALITY_LOOKBACK_DAYS = 7
QUALITY_MIN_SMART_SCORE = 60.0
QUALITY_TARGET_COPY_SIZE_SOL = 0.05
QUALITY_DUST_THRESHOLD_SOL = 0.001
QUALITY_MEANINGFUL_THRESHOLD_SOL = 0.005
QUALITY_SIZE_COMPATIBLE_MIN_SOL = 0.02
QUALITY_SIZE_COMPATIBLE_MAX_SOL = 5.0
QUALITY_MIN_SAMPLE_SWAPS = 4
QUALITY_COPYABLE_MIN_SAMPLE_SWAPS = 4
QUALITY_COPYABLE_MIN_MEANINGFUL_SWAPS = 4
QUALITY_COPYABLE_MIN_ACTIVE_DAYS = 2
QUALITY_COPYABLE_MAX_DUST_RATIO = 0.25
QUALITY_COPYABLE_MIN_SIZE_RATIO = 0.50
QUALITY_COPYABLE_MIN_SIDE_BALANCE = 20.0
QUALITY_COPYABLE_MAX_TOKEN_CONCENTRATION = 0.85
QUALITY_SUSPICIOUS_MIN_SAMPLE = 10
QUALITY_SUSPICIOUS_DUST_RATIO = 0.70
QUALITY_SUSPICIOUS_MEANINGFUL_RATIO = 0.25
QUALITY_SUSPICIOUS_TOKEN_CONCENTRATION = 0.95
QUALITY_SUSPICIOUS_ONE_SIDED_SWAPS = 10


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _round(value: float, digits: int = 8) -> float:
    return round(float(value or 0.0), digits)


def _side_balance_score(buys: int, sells: int) -> float:
    maximum = max(buys, sells)
    if maximum <= 0:
        return 0.0
    return round(min(buys, sells) / maximum * 100.0, 4)


def _size_compatibility_score(amount: float) -> float:
    if amount <= 0:
        return 0.0
    if QUALITY_SIZE_COMPATIBLE_MIN_SOL <= amount <= QUALITY_SIZE_COMPATIBLE_MAX_SOL:
        return 100.0
    if QUALITY_DUST_THRESHOLD_SOL < amount < QUALITY_SIZE_COMPATIBLE_MIN_SOL:
        return clamp(
            (amount - QUALITY_DUST_THRESHOLD_SOL)
            / (QUALITY_SIZE_COMPATIBLE_MIN_SOL - QUALITY_DUST_THRESHOLD_SOL)
            * 100.0
        )
    if amount > QUALITY_SIZE_COMPATIBLE_MAX_SOL:
        return clamp(100.0 - (amount - QUALITY_SIZE_COMPATIBLE_MAX_SOL) * 5.0)
    return 0.0


def _quality_score(
    *,
    sample_swaps: int,
    meaningful_swaps: int,
    dust_ratio: float,
    size_compatibility_ratio: float,
    side_balance_score: float,
    round_trip_token_ratio: float,
    unique_tokens: int,
    top_token_concentration: float,
    activity_classification: str,
    one_sided_pattern: bool,
) -> float:
    sample_component = min(meaningful_swaps / 20.0, 1.0) * 15.0
    dust_component = max(0.0, 1.0 - dust_ratio) * 20.0
    size_component = clamp(size_compatibility_ratio * 100.0) / 100.0 * 15.0
    side_component = clamp(side_balance_score) / 100.0 * 15.0
    round_trip_component = clamp(round_trip_token_ratio * 100.0) / 100.0 * 15.0
    diversity_component = min(unique_tokens / 5.0, 1.0) * 10.0
    activity_component = {
        ACTIVITY_CLASS_ACTIVE: 10.0,
        ACTIVITY_CLASS_LOW: 5.0,
    }.get(activity_classification, 0.0)

    score = (
        sample_component
        + dust_component
        + size_component
        + side_component
        + round_trip_component
        + diversity_component
        + activity_component
    )

    if top_token_concentration > 0.75:
        score -= min(15.0, (top_token_concentration - 0.75) / 0.25 * 15.0)
    if one_sided_pattern:
        score -= 25.0
    if (
        sample_swaps >= QUALITY_SUSPICIOUS_MIN_SAMPLE
        and dust_ratio >= QUALITY_SUSPICIOUS_DUST_RATIO
    ):
        score -= 30.0

    return round(clamp(score), 4)


def analyze_wallet_quality_from_trades(
    wallet_address: str,
    recent_trades: Iterable[Trade],
    *,
    smart_score: float,
    activity: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    calculated_at = ensure_aware(now) or utc_now()
    cutoff = calculated_at - timedelta(days=QUALITY_LOOKBACK_DAYS)
    trades = sorted(
        (
            trade
            for trade in recent_trades
            if bool(trade.success)
            and ensure_aware(trade.block_time) is not None
            and ensure_aware(trade.block_time) >= cutoff
        ),
        key=lambda trade: (
            ensure_aware(trade.block_time),
            int(trade.id or 0),
        ),
    )

    amounts: list[float] = []
    token_sides: dict[str, set[str]] = defaultdict(set)
    token_counts: Counter[str] = Counter()
    buys = 0
    sells = 0
    invalid_amounts = 0

    for trade in trades:
        side = str(trade.side or "UNKNOWN").strip().upper()
        if side == "BUY":
            buys += 1
        elif side == "SELL":
            sells += 1

        amount = abs(safe_float(trade.sol_amount))
        if amount <= 0:
            invalid_amounts += 1
        amounts.append(amount)

        token = str(trade.token_mint or "").strip()
        if token:
            token_counts[token] += 1
            if side in {"BUY", "SELL"}:
                token_sides[token].add(side)

    sample_swaps = len(trades)
    meaningful_swaps = sum(
        1 for amount in amounts if amount >= QUALITY_MEANINGFUL_THRESHOLD_SOL
    )
    dust_swaps = sum(
        1 for amount in amounts if 0 < amount <= QUALITY_DUST_THRESHOLD_SOL
    )
    size_compatible_swaps = sum(
        1
        for amount in amounts
        if QUALITY_SIZE_COMPATIBLE_MIN_SOL
        <= amount
        <= QUALITY_SIZE_COMPATIBLE_MAX_SOL
    )

    total_volume = sum(amounts)
    average_swap = total_volume / sample_swaps if sample_swaps else 0.0
    median_swap = median(amounts) if amounts else 0.0
    dust_ratio = dust_swaps / sample_swaps if sample_swaps else 0.0
    meaningful_ratio = meaningful_swaps / sample_swaps if sample_swaps else 0.0
    size_compatibility_ratio = (
        size_compatible_swaps / sample_swaps if sample_swaps else 0.0
    )
    average_size_compatibility_score = (
        sum(_size_compatibility_score(amount) for amount in amounts) / sample_swaps
        if sample_swaps
        else 0.0
    )

    unique_tokens = len(token_counts)
    top_token_concentration = (
        max(token_counts.values()) / sum(token_counts.values())
        if token_counts
        else 0.0
    )
    completed_token_pairs = sum(
        1 for sides in token_sides.values() if {"BUY", "SELL"}.issubset(sides)
    )
    round_trip_token_ratio = (
        completed_token_pairs / unique_tokens if unique_tokens else 0.0
    )
    side_balance_score = _side_balance_score(buys, sells)
    one_sided_pattern = (
        sample_swaps >= QUALITY_SUSPICIOUS_ONE_SIDED_SWAPS
        and (buys == 0 or sells == 0)
    )

    activity_classification = str(
        activity.get("activity_classification") or "NON_ANALIZZATO"
    )
    active_days = int(activity.get("active_days_7d") or 0)
    last_swap_at = ensure_aware(activity.get("last_swap_at"))

    reasons: list[str] = []
    if activity_classification == ACTIVITY_CLASS_INACTIVE:
        reasons.append("INACTIVE_WALLET")
    elif activity_classification == ACTIVITY_CLASS_HYPERACTIVE:
        reasons.append("HYPERACTIVE_WALLET")
    elif activity_classification == ACTIVITY_CLASS_LOW:
        reasons.append("LOW_RECENT_ACTIVITY")

    if sample_swaps < QUALITY_MIN_SAMPLE_SWAPS:
        reasons.append("INSUFFICIENT_QUALITY_SAMPLE")
    if meaningful_swaps < QUALITY_COPYABLE_MIN_MEANINGFUL_SWAPS:
        reasons.append("INSUFFICIENT_MEANINGFUL_SWAPS")
    if dust_ratio > QUALITY_COPYABLE_MAX_DUST_RATIO:
        reasons.append("DUST_RATIO_HIGH")
    if median_swap < QUALITY_SIZE_COMPATIBLE_MIN_SOL and sample_swaps:
        reasons.append("MEDIAN_SWAP_BELOW_COPY_SIZE")
    if size_compatibility_ratio < QUALITY_COPYABLE_MIN_SIZE_RATIO:
        reasons.append("LOW_SIZE_COMPATIBILITY")
    if buys == 0:
        reasons.append("NO_RECENT_BUYS")
    if sells == 0:
        reasons.append("NO_RECENT_SELLS")
    if one_sided_pattern:
        reasons.append("ONE_SIDED_SWAP_PATTERN")
    if side_balance_score < QUALITY_COPYABLE_MIN_SIDE_BALANCE and sample_swaps:
        reasons.append("BUY_SELL_IMBALANCE")
    if unique_tokens < 2:
        reasons.append("LOW_TOKEN_DIVERSITY")
    if top_token_concentration > QUALITY_COPYABLE_MAX_TOKEN_CONCENTRATION:
        reasons.append("TOKEN_CONCENTRATION_HIGH")
    if completed_token_pairs == 0 and unique_tokens > 0:
        reasons.append("NO_COMPLETE_BUY_SELL_CYCLE")
    if active_days < QUALITY_COPYABLE_MIN_ACTIVE_DAYS:
        reasons.append("INSUFFICIENT_ACTIVE_DAYS")
    if invalid_amounts:
        reasons.append("INVALID_OR_ZERO_SWAP_AMOUNT")
    if safe_float(smart_score) < QUALITY_MIN_SMART_SCORE:
        reasons.append("SMART_SCORE_BELOW_QUALITY_MINIMUM")
    if last_swap_at is None:
        reasons.append("LAST_SWAP_NOT_AVAILABLE")

    suspicious = any(
        (
            one_sided_pattern,
            (
                sample_swaps >= QUALITY_SUSPICIOUS_MIN_SAMPLE
                and dust_ratio >= QUALITY_SUSPICIOUS_DUST_RATIO
            ),
            (
                sample_swaps >= QUALITY_SUSPICIOUS_MIN_SAMPLE
                and meaningful_ratio < QUALITY_SUSPICIOUS_MEANINGFUL_RATIO
            ),
            (
                sample_swaps >= 20
                and top_token_concentration
                >= QUALITY_SUSPICIOUS_TOKEN_CONCENTRATION
            ),
        )
    )

    score = _quality_score(
        sample_swaps=sample_swaps,
        meaningful_swaps=meaningful_swaps,
        dust_ratio=dust_ratio,
        size_compatibility_ratio=size_compatibility_ratio,
        side_balance_score=side_balance_score,
        round_trip_token_ratio=round_trip_token_ratio,
        unique_tokens=unique_tokens,
        top_token_concentration=top_token_concentration,
        activity_classification=activity_classification,
        one_sided_pattern=one_sided_pattern,
    )

    copyable = all(
        (
            activity_classification == ACTIVITY_CLASS_ACTIVE,
            safe_float(smart_score) >= QUALITY_MIN_SMART_SCORE,
            sample_swaps >= QUALITY_COPYABLE_MIN_SAMPLE_SWAPS,
            meaningful_swaps >= QUALITY_COPYABLE_MIN_MEANINGFUL_SWAPS,
            dust_ratio <= QUALITY_COPYABLE_MAX_DUST_RATIO,
            median_swap >= QUALITY_SIZE_COMPATIBLE_MIN_SOL,
            size_compatibility_ratio >= QUALITY_COPYABLE_MIN_SIZE_RATIO,
            buys > 0,
            sells > 0,
            side_balance_score >= QUALITY_COPYABLE_MIN_SIDE_BALANCE,
            unique_tokens >= 2,
            top_token_concentration <= QUALITY_COPYABLE_MAX_TOKEN_CONCENTRATION,
            completed_token_pairs >= 1,
            round_trip_token_ratio >= 0.25,
            active_days >= QUALITY_COPYABLE_MIN_ACTIVE_DAYS,
            not suspicious,
        )
    )

    if activity_classification in {
        ACTIVITY_CLASS_INACTIVE,
        ACTIVITY_CLASS_HYPERACTIVE,
    }:
        classification = QUALITY_CLASS_NOT_COPYABLE
    elif suspicious:
        classification = QUALITY_CLASS_SUSPICIOUS
    elif copyable:
        classification = QUALITY_CLASS_COPYABLE
    else:
        classification = QUALITY_CLASS_OBSERVATION

    return {
        "wallet_address": wallet_address,
        "quality_score": score,
        "quality_classification": classification,
        "quality_eligible": classification == QUALITY_CLASS_COPYABLE,
        "quality_reasons": list(dict.fromkeys(reasons)),
        "quality_calculated_at": calculated_at,
        "quality_sample_swaps_7d": sample_swaps,
        "meaningful_swaps_7d": meaningful_swaps,
        "dust_swaps_7d": dust_swaps,
        "dust_ratio_7d": _round(dust_ratio, 6),
        "average_swap_sol_7d": _round(average_swap),
        "median_swap_sol_7d": _round(median_swap),
        "size_compatible_swaps_7d": size_compatible_swaps,
        "size_compatibility_ratio_7d": _round(size_compatibility_ratio, 6),
        "average_size_compatibility_score_7d": _round(
            average_size_compatibility_score, 4
        ),
        "buy_sell_balance_score_7d": _round(side_balance_score, 4),
        "unique_tokens_7d": unique_tokens,
        "top_token_concentration_7d": _round(top_token_concentration, 6),
        "completed_token_pairs_7d": completed_token_pairs,
        "round_trip_token_ratio_7d": _round(round_trip_token_ratio, 6),
        "invalid_amount_swaps_7d": invalid_amounts,
        "target_copy_size_sol": QUALITY_TARGET_COPY_SIZE_SOL,
    }


def analyze_wallet_quality(
    db: Session,
    wallet_address: str,
    *,
    smart_score: float,
    activity: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    calculated_at = ensure_aware(now) or utc_now()
    cutoff = calculated_at - timedelta(days=QUALITY_LOOKBACK_DAYS)
    trades = (
        db.query(Trade)
        .filter(Trade.wallet_address == wallet_address)
        .filter(Trade.success.is_(True))
        .filter(Trade.block_time.isnot(None))
        .filter(Trade.block_time >= cutoff)
        .order_by(Trade.block_time.asc(), Trade.id.asc())
        .all()
    )
    return analyze_wallet_quality_from_trades(
        wallet_address,
        trades,
        smart_score=smart_score,
        activity=activity,
        now=calculated_at,
    )
