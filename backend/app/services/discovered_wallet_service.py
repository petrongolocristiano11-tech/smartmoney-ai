from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.services.wallet_activity_service import (
    analyze_wallet_activity,
    build_discovery_ranking,
)


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


def apply_activity_and_ranking(
    wallet: DiscoveredWallet,
    *,
    smart_score: float,
    activity: dict[str, Any],
) -> DiscoveredWallet:
    for field in ACTIVITY_FIELDS:
        if field in activity:
            setattr(wallet, field, activity[field])

    ranking = build_discovery_ranking(
        smart_score=smart_score,
        activity=activity,
    )
    wallet.ranking_score = ranking["ranking_score"]
    wallet.eligible = ranking["eligible"]
    wallet.eligibility_reasons = ranking["eligibility_reasons"]
    return wallet


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
    apply_activity_and_ranking(
        wallet,
        smart_score=smart_score,
        activity=activity,
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
        apply_activity_and_ranking(
            wallet,
            smart_score=wallet.smart_score,
            activity=activity,
        )
        wallet.status = "UPDATED"
        refreshed += 1

    db.commit()
    return {
        "status": "COMPLETED",
        "wallets_refreshed": refreshed,
        "helius_requests": 0,
        "message": (
            "Ranking attività ricalcolato usando esclusivamente i trade già presenti "
            "nel database. Nessuna richiesta Helius eseguita."
        ),
    }
