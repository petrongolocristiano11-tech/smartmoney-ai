from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.services.wallet_activity_service import (
    analyze_wallet_activity,
    build_discovery_ranking,
)
from backend.app.services.wallet_quality_service import analyze_wallet_quality


ACTIVITY_FIELDS = (
    "last_swap_at",
    "swaps_24h",
    "swaps_7d",
    "buys_24h",
    "sells_24h",
    "buys_7d",
    "sells_7d",
    "volume_24h_sol",
    "volume_7d_sol",
    "active_days_7d",
    "average_swaps_per_active_day_7d",
    "average_minutes_between_swaps_7d",
    "activity_score",
    "activity_classification",
    "activity_eligible",
    "activity_reasons",
    "activity_calculated_at",
)

QUALITY_FIELDS = (
    "quality_score",
    "quality_classification",
    "quality_eligible",
    "quality_reasons",
    "quality_calculated_at",
    "quality_sample_swaps_7d",
    "meaningful_swaps_7d",
    "dust_swaps_7d",
    "dust_ratio_7d",
    "average_swap_sol_7d",
    "median_swap_sol_7d",
    "size_compatible_swaps_7d",
    "size_compatibility_ratio_7d",
    "average_size_compatibility_score_7d",
    "buy_sell_balance_score_7d",
    "unique_tokens_7d",
    "top_token_concentration_7d",
    "completed_token_pairs_7d",
    "round_trip_token_ratio_7d",
    "invalid_amount_swaps_7d",
)


def apply_activity_quality_and_ranking(
    wallet: DiscoveredWallet,
    *,
    smart_score: float,
    activity: dict[str, Any],
    quality: dict[str, Any],
) -> DiscoveredWallet:
    for field in ACTIVITY_FIELDS:
        if field in activity:
            setattr(wallet, field, activity[field])
    for field in QUALITY_FIELDS:
        if field in quality:
            setattr(wallet, field, quality[field])

    ranking = build_discovery_ranking(
        smart_score=smart_score,
        activity=activity,
        quality=quality,
    )
    wallet.ranking_score = ranking["ranking_score"]
    wallet.eligible = bool(
        ranking["eligible"]
        and wallet.promotion_eligible
        and wallet.backtest_data_sufficient
    )
    reasons = list(ranking["eligibility_reasons"])
    reasons.extend(wallet.promotion_reasons or [])
    if not wallet.backtest_data_sufficient:
        reasons.extend(wallet.backtest_data_sufficiency_reasons or [])
        reasons.append("BACKTEST_DATA_INSUFFICIENT")
    if not wallet.promotion_eligible:
        reasons.append("PROMOTION_GATE_NOT_PASSED")
    wallet.eligibility_reasons = list(dict.fromkeys(reasons))
    return wallet


def apply_activity_and_ranking(
    wallet: DiscoveredWallet,
    *,
    smart_score: float,
    activity: dict[str, Any],
    quality: dict[str, Any] | None = None,
) -> DiscoveredWallet:
    for field in ACTIVITY_FIELDS:
        if field in activity:
            setattr(wallet, field, activity[field])

    ranking = build_discovery_ranking(
        smart_score=smart_score,
        activity=activity,
        quality=quality,
    )
    wallet.ranking_score = ranking["ranking_score"]
    wallet.eligible = bool(
        ranking["eligible"]
        and wallet.promotion_eligible
        and wallet.backtest_data_sufficient
    )
    reasons = list(ranking["eligibility_reasons"])
    reasons.extend(wallet.promotion_reasons or [])
    if not wallet.backtest_data_sufficient:
        reasons.extend(wallet.backtest_data_sufficiency_reasons or [])
        reasons.append("BACKTEST_DATA_INSUFFICIENT")
    if not wallet.promotion_eligible:
        reasons.append("PROMOTION_GATE_NOT_PASSED")
    wallet.eligibility_reasons = list(dict.fromkeys(reasons))
    return wallet


def analyze_and_apply_wallet_ranking(
    db: Session,
    wallet: DiscoveredWallet,
    *,
    activity: dict[str, Any] | None = None,
) -> DiscoveredWallet:
    resolved_activity = activity or analyze_wallet_activity(
        db,
        wallet.wallet_address,
    )
    quality = analyze_wallet_quality(
        db,
        wallet.wallet_address,
        smart_score=wallet.smart_score,
        activity=resolved_activity,
    )
    return apply_activity_quality_and_ranking(
        wallet,
        smart_score=wallet.smart_score,
        activity=resolved_activity,
        quality=quality,
    )


def save_discovered_wallet(
    db: Session,
    wallet_address: str,
    discovered_from_token: str,
    smart_score: float,
    roi_percent: float,
    win_rate_percent: float,
    profit_loss_sol: float,
    reliable_positions: int,
    activity: dict[str, Any],
):
    wallet = (
        db.query(DiscoveredWallet)
        .filter(DiscoveredWallet.wallet_address == wallet_address)
        .first()
    )

    if wallet is None:
        wallet = DiscoveredWallet(wallet_address=wallet_address)
        db.add(wallet)
        wallet.status = "DISCOVERED"
    else:
        wallet.status = "UPDATED"

    wallet.smart_score = smart_score
    wallet.roi_percent = roi_percent
    wallet.win_rate_percent = win_rate_percent
    wallet.profit_loss_sol = profit_loss_sol
    wallet.reliable_positions = reliable_positions
    wallet.discovered_from_token = discovered_from_token
    quality = analyze_wallet_quality(
        db,
        wallet_address,
        smart_score=smart_score,
        activity=activity,
    )
    apply_activity_quality_and_ranking(
        wallet,
        smart_score=smart_score,
        activity=activity,
        quality=quality,
    )

    db.commit()
    db.refresh(wallet)
    return wallet


def refresh_discovered_wallet_activity(
    db: Session,
    *,
    limit: int = 250,
) -> dict[str, Any]:
    wallets = (
        db.query(DiscoveredWallet)
        .order_by(DiscoveredWallet.updated_at.desc(), DiscoveredWallet.id.asc())
        .limit(limit)
        .all()
    )

    refreshed = 0
    for wallet in wallets:
        activity = analyze_wallet_activity(db, wallet.wallet_address)
        analyze_and_apply_wallet_ranking(db, wallet, activity=activity)
        wallet.status = "UPDATED"
        refreshed += 1

    db.commit()
    return {
        "status": "COMPLETED",
        "wallets_refreshed": refreshed,
        "helius_requests": 0,
        "message": (
            "Attività, qualità e ranking ricalcolati usando esclusivamente i "
            "trade già presenti nel database. Nessuna richiesta Helius eseguita."
        ),
    }


def refresh_discovered_wallet_quality(
    db: Session,
    *,
    limit: int = 250,
) -> dict[str, Any]:
    wallets = (
        db.query(DiscoveredWallet)
        .order_by(DiscoveredWallet.updated_at.desc(), DiscoveredWallet.id.asc())
        .limit(limit)
        .all()
    )

    classifications: Counter[str] = Counter()
    for wallet in wallets:
        analyze_and_apply_wallet_ranking(db, wallet)
        wallet.status = "UPDATED"
        classifications[wallet.quality_classification] += 1

    db.commit()
    return {
        "status": "COMPLETED",
        "wallets_refreshed": len(wallets),
        "helius_requests": 0,
        "copyable": classifications["COPIABILE"],
        "observation": classifications["OSSERVAZIONE"],
        "suspicious": classifications["SOSPETTO"],
        "not_copyable": classifications["NON_COPIABILE"],
        "not_analyzed": classifications["NON_ANALIZZATO"],
        "message": (
            "Qualità di esecuzione ricalcolata dal database: nessuna richiesta "
            "Helius, nessuna modifica a LIVE, stream, worker o generazioni."
        ),
    }
