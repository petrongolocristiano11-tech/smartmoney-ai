from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import log1p
from typing import Any

from sqlalchemy.orm import Session

from backend.app.models.trade import Trade


ACTIVITY_CLASS_ACTIVE = "ATTIVO"
ACTIVITY_CLASS_LOW = "POCO_ATTIVO"
ACTIVITY_CLASS_INACTIVE = "INATTIVO"
ACTIVITY_CLASS_HYPERACTIVE = "IPERATTIVO"
ACTIVITY_CLASS_NOT_ANALYZED = "NON_ANALIZZATO"

DISCOVERY_MIN_SMART_SCORE = 60.0
ACTIVE_RECENCY_HOURS = 72
INACTIVE_AFTER_DAYS = 7
MIN_ACTIVE_SWAPS_7D = 3
MIN_ACTIVE_DAYS_7D = 2
HYPERACTIVE_SWAPS_24H = 40
HYPERACTIVE_SWAPS_7D = 120
HYPERACTIVE_AVERAGE_SWAPS_PER_ACTIVE_DAY = 30.0
HYPERACTIVE_MINIMUM_BURST_SWAPS_24H = 20
HYPERACTIVE_MINIMUM_AVERAGE_MINUTES = 2.0


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(float(value), maximum))


def _average_minutes_between_swaps(timestamps: list[datetime]) -> float | None:
    ordered = sorted({ensure_aware(item) for item in timestamps if item is not None})
    ordered = [item for item in ordered if item is not None]

    if len(ordered) < 2:
        return None

    differences = [
        (current - previous).total_seconds() / 60
        for previous, current in zip(ordered, ordered[1:])
        if current >= previous
    ]
    if not differences:
        return None

    return round(sum(differences) / len(differences), 4)


def _classify_activity(
    *,
    now: datetime,
    last_swap_at: datetime | None,
    swaps_24h: int,
    swaps_7d: int,
    active_days_7d: int,
    average_swaps_per_active_day_7d: float,
    average_minutes_between_swaps_7d: float | None,
) -> str:
    if last_swap_at is None or swaps_7d == 0:
        return ACTIVITY_CLASS_INACTIVE

    last_swap_at = ensure_aware(last_swap_at)
    if last_swap_at is None or last_swap_at < now - timedelta(days=INACTIVE_AFTER_DAYS):
        return ACTIVITY_CLASS_INACTIVE

    is_hyperactive = any(
        (
            swaps_24h >= HYPERACTIVE_SWAPS_24H,
            swaps_7d >= HYPERACTIVE_SWAPS_7D,
            average_swaps_per_active_day_7d
            >= HYPERACTIVE_AVERAGE_SWAPS_PER_ACTIVE_DAY,
            (
                average_minutes_between_swaps_7d is not None
                and average_minutes_between_swaps_7d
                <= HYPERACTIVE_MINIMUM_AVERAGE_MINUTES
                and swaps_24h >= HYPERACTIVE_MINIMUM_BURST_SWAPS_24H
            ),
        )
    )
    if is_hyperactive:
        return ACTIVITY_CLASS_HYPERACTIVE

    is_recent = last_swap_at >= now - timedelta(hours=ACTIVE_RECENCY_HOURS)
    if (
        is_recent
        and swaps_7d >= MIN_ACTIVE_SWAPS_7D
        and active_days_7d >= MIN_ACTIVE_DAYS_7D
    ):
        return ACTIVITY_CLASS_ACTIVE

    return ACTIVITY_CLASS_LOW


def _activity_score(
    *,
    now: datetime,
    last_swap_at: datetime | None,
    swaps_7d: int,
    buys_7d: int,
    sells_7d: int,
    volume_7d_sol: float,
    active_days_7d: int,
    classification: str,
) -> float:
    if last_swap_at is None:
        return 0.0

    last_swap_at = ensure_aware(last_swap_at)
    if last_swap_at is None:
        return 0.0

    recency_hours = max(0.0, (now - last_swap_at).total_seconds() / 3600)
    recency_score = 35.0 * max(0.0, 1.0 - recency_hours / (24 * 7))
    swap_score = min(swaps_7d, 20) / 20 * 25.0
    active_days_score = min(active_days_7d, 5) / 5 * 20.0

    if buys_7d > 0 and sells_7d > 0:
        side_score = 10.0
    elif buys_7d > 0 or sells_7d > 0:
        side_score = 5.0
    else:
        side_score = 0.0

    volume_score = min(log1p(max(0.0, volume_7d_sol)) / log1p(50.0), 1.0) * 10.0
    score = recency_score + swap_score + active_days_score + side_score + volume_score

    if classification == ACTIVITY_CLASS_INACTIVE:
        score = min(score, 15.0)
    elif classification == ACTIVITY_CLASS_LOW:
        score = min(score, 55.0)
    elif classification == ACTIVITY_CLASS_HYPERACTIVE:
        score = min(score, 40.0)

    return round(clamp(score), 4)


def analyze_wallet_activity(
    db: Session,
    wallet_address: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    calculated_at = ensure_aware(now) or utc_now()
    cutoff_24h = calculated_at - timedelta(hours=24)
    cutoff_7d = calculated_at - timedelta(days=7)

    latest_trade = (
        db.query(Trade)
        .filter(Trade.wallet_address == wallet_address)
        .filter(Trade.success.is_(True))
        .filter(Trade.block_time.isnot(None))
        .order_by(Trade.block_time.desc(), Trade.id.desc())
        .first()
    )

    recent_trades = (
        db.query(Trade)
        .filter(Trade.wallet_address == wallet_address)
        .filter(Trade.success.is_(True))
        .filter(Trade.block_time.isnot(None))
        .filter(Trade.block_time >= cutoff_7d)
        .order_by(Trade.block_time.asc(), Trade.id.asc())
        .all()
    )

    swaps_24h = 0
    buys_24h = 0
    sells_24h = 0
    buys_7d = 0
    sells_7d = 0
    volume_24h_sol = 0.0
    volume_7d_sol = 0.0
    active_days: set = set()
    timestamps: list[datetime] = []

    for trade in recent_trades:
        block_time = ensure_aware(trade.block_time)
        if block_time is None:
            continue

        timestamps.append(block_time)
        active_days.add(block_time.date())

        side = str(trade.side or "UNKNOWN").strip().upper()
        amount = abs(safe_float(trade.sol_amount))

        volume_7d_sol += amount
        if side == "BUY":
            buys_7d += 1
        elif side == "SELL":
            sells_7d += 1

        if block_time >= cutoff_24h:
            swaps_24h += 1
            volume_24h_sol += amount
            if side == "BUY":
                buys_24h += 1
            elif side == "SELL":
                sells_24h += 1

    swaps_7d = len(recent_trades)
    active_days_7d = len(active_days)
    average_swaps_per_active_day_7d = (
        round(swaps_7d / active_days_7d, 4) if active_days_7d else 0.0
    )
    average_minutes_between_swaps_7d = _average_minutes_between_swaps(timestamps)
    last_swap_at = ensure_aware(latest_trade.block_time) if latest_trade else None

    classification = _classify_activity(
        now=calculated_at,
        last_swap_at=last_swap_at,
        swaps_24h=swaps_24h,
        swaps_7d=swaps_7d,
        active_days_7d=active_days_7d,
        average_swaps_per_active_day_7d=average_swaps_per_active_day_7d,
        average_minutes_between_swaps_7d=average_minutes_between_swaps_7d,
    )
    activity_score = _activity_score(
        now=calculated_at,
        last_swap_at=last_swap_at,
        swaps_7d=swaps_7d,
        buys_7d=buys_7d,
        sells_7d=sells_7d,
        volume_7d_sol=volume_7d_sol,
        active_days_7d=active_days_7d,
        classification=classification,
    )

    reasons: list[str] = []
    if classification == ACTIVITY_CLASS_INACTIVE:
        reasons.append("INACTIVE_WALLET")
    elif classification == ACTIVITY_CLASS_HYPERACTIVE:
        reasons.append("HYPERACTIVE_WALLET")
    elif classification == ACTIVITY_CLASS_LOW:
        reasons.append("LOW_RECENT_ACTIVITY")

    if buys_7d == 0:
        reasons.append("NO_RECENT_BUYS")
    if sells_7d == 0:
        reasons.append("NO_RECENT_SELLS")

    return {
        "wallet_address": wallet_address,
        "last_swap_at": last_swap_at,
        "swaps_24h": swaps_24h,
        "swaps_7d": swaps_7d,
        "buys_24h": buys_24h,
        "sells_24h": sells_24h,
        "buys_7d": buys_7d,
        "sells_7d": sells_7d,
        "volume_24h_sol": round(volume_24h_sol, 8),
        "volume_7d_sol": round(volume_7d_sol, 8),
        "active_days_7d": active_days_7d,
        "average_swaps_per_active_day_7d": average_swaps_per_active_day_7d,
        "average_minutes_between_swaps_7d": average_minutes_between_swaps_7d,
        "activity_score": activity_score,
        "activity_classification": classification,
        "activity_eligible": classification
        not in {ACTIVITY_CLASS_INACTIVE, ACTIVITY_CLASS_HYPERACTIVE},
        "activity_reasons": reasons,
        "activity_calculated_at": calculated_at,
    }


def build_discovery_ranking(
    *,
    smart_score: float,
    activity: dict[str, Any],
    minimum_smart_score: float = DISCOVERY_MIN_SMART_SCORE,
) -> dict[str, Any]:
    normalized_smart_score = clamp(safe_float(smart_score))
    activity_score = clamp(safe_float(activity.get("activity_score")))
    ranking_score = round(
        normalized_smart_score * 0.75 + activity_score * 0.25,
        4,
    )

    reasons = list(activity.get("activity_reasons") or [])
    if normalized_smart_score < minimum_smart_score:
        reasons.append("SMART_SCORE_BELOW_MINIMUM")

    eligible = bool(activity.get("activity_eligible")) and (
        normalized_smart_score >= minimum_smart_score
    )

    return {
        "ranking_score": ranking_score,
        "eligible": eligible,
        "eligibility_reasons": list(dict.fromkeys(reasons)),
        "minimum_smart_score": minimum_smart_score,
    }
