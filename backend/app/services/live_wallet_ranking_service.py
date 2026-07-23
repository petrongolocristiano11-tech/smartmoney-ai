from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.models.live_copy_order import LiveCopyOrder
from backend.app.models.live_wallet_score import LiveWalletScore
from backend.app.models.wallet_profile import WalletProfile
from backend.app.services.live_order_attribution import (
    MANUAL_DRY_RUN_CLOSE_WALLET,
    is_manual_close_wallet,
)
from backend.app.services.live_platform_config_service import get_or_create_platform_config
from backend.app.services.live_trading_errors import LiveTradingError
from backend.app.services.live_trading_policy_service import (
    get_or_create_live_policy,
    record_live_event,
)


PNL_EPSILON = 1e-12
MAX_RANKING_ROWS = 50
COMPLETED_STATUSES = ("DRY_RUN", "FILLED")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def safe_float(value) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(float(value), maximum))


def normalize_performance_score(
    *,
    win_rate_percent: float,
    roi_percent: float,
    realized_pnl_sol: float,
    closed_trades: int,
) -> float:
    sample_score = clamp(closed_trades / 20 * 100)
    roi_score = clamp(50 + roi_percent / 2)
    pnl_score = clamp(50 + realized_pnl_sol * 100)

    return round(
        clamp(
            win_rate_percent * 0.40
            + roi_score * 0.25
            + pnl_score * 0.20
            + sample_score * 0.15
        ),
        4,
    )


def _resolved_order_wallets(orders: list[LiveCopyOrder]) -> dict[int, str]:
    latest_buy_wallet: dict[tuple[str, int, str], str] = {}

    for order in sorted(orders, key=lambda item: (item.created_at, item.id)):
        wallet = str(order.source_wallet or "").strip()
        token = str(order.source_token_mint or "").strip()
        if (
            order.source_side == "BUY"
            and wallet
            and token
            and not is_manual_close_wallet(wallet)
        ):
            latest_buy_wallet[(order.mode, int(order.generation), token)] = wallet

    resolved: dict[int, str] = {}
    for order in orders:
        wallet = str(order.source_wallet or "").strip()
        if is_manual_close_wallet(wallet):
            wallet = latest_buy_wallet.get(
                (
                    order.mode,
                    int(order.generation),
                    str(order.source_token_mint or "").strip(),
                ),
                wallet,
            )
        resolved[order.id] = wallet
    return resolved


def _activity_reasons(discovered: DiscoveredWallet | None) -> list[str]:
    if discovered is None:
        return ["ACTIVITY_NOT_ANALYZED"]

    reasons: list[str] = []
    if discovered.activity_classification == "INATTIVO":
        reasons.append("INACTIVE_WALLET")
    elif discovered.activity_classification == "IPERATTIVO":
        reasons.append("HYPERACTIVE_WALLET")
    elif discovered.activity_classification == "POCO_ATTIVO":
        reasons.append("LOW_RECENT_ACTIVITY")
    return reasons


def _quality_reasons(discovered: DiscoveredWallet | None) -> list[str]:
    if discovered is None:
        return ["QUALITY_NOT_ANALYZED"]

    reasons = list(discovered.quality_reasons or [])
    if discovered.quality_classification == "NON_ANALIZZATO":
        reasons.append("QUALITY_NOT_ANALYZED")
    elif discovered.quality_classification == "OSSERVAZIONE":
        reasons.append("QUALITY_OBSERVATION_ONLY")
    elif discovered.quality_classification == "SOSPETTO":
        reasons.append("SUSPICIOUS_WALLET_QUALITY")
    elif discovered.quality_classification == "NON_COPIABILE":
        reasons.append("WALLET_NOT_COPYABLE")
    return list(dict.fromkeys(reasons))


def _promotion_reasons(discovered: DiscoveredWallet | None) -> list[str]:
    if discovered is None:
        return ["PROMOTION_DATA_NOT_AVAILABLE"]
    reasons = list(discovered.promotion_reasons or [])
    if not discovered.promotion_eligible:
        reasons.append("PROMOTION_GATE_NOT_PASSED")
    return list(dict.fromkeys(reasons))


def refresh_live_wallet_ranking(db: Session) -> list[LiveWalletScore]:
    policy = get_or_create_live_policy(db)
    config = get_or_create_platform_config(db)

    completed_orders = (
        db.query(LiveCopyOrder)
        .filter(LiveCopyOrder.status.in_(COMPLETED_STATUSES))
        .order_by(LiveCopyOrder.created_at.asc(), LiveCopyOrder.id.asc())
        .all()
    )
    resolved_wallets = _resolved_order_wallets(completed_orders)

    candidate_wallets: set[str] = {
        str(wallet).strip()
        for wallet in (policy.source_wallets or [])
        if str(wallet).strip()
    }
    candidate_wallets.update(
        wallet
        for wallet in resolved_wallets.values()
        if wallet and wallet != MANUAL_DRY_RUN_CLOSE_WALLET
    )
    candidate_wallets.update(
        address
        for (address,) in db.query(WalletProfile.wallet_address).all()
        if address
    )
    candidate_wallets.update(
        address
        for (address,) in db.query(DiscoveredWallet.wallet_address).all()
        if address
    )
    candidate_wallets = {
        wallet for wallet in candidate_wallets if 32 <= len(wallet) <= 44
    }

    stale_query = db.query(LiveWalletScore)
    if candidate_wallets:
        stale_query.filter(
            ~LiveWalletScore.wallet_address.in_(candidate_wallets)
        ).delete(synchronize_session=False)
    else:
        stale_query.delete(synchronize_session=False)

    profile_map = {
        profile.wallet_address: profile
        for profile in db.query(WalletProfile)
        .filter(WalletProfile.wallet_address.in_(candidate_wallets or ["__none__"]))
        .all()
    }
    activity_map = {
        wallet.wallet_address: wallet
        for wallet in db.query(DiscoveredWallet)
        .filter(DiscoveredWallet.wallet_address.in_(candidate_wallets or ["__none__"]))
        .all()
    }

    stats: dict[str, dict] = defaultdict(
        lambda: {
            "buy_value": 0.0,
            "pnl": 0.0,
            "wins": 0,
            "losses": 0,
            "closed": 0,
        }
    )

    for order in completed_orders:
        wallet = resolved_wallets.get(order.id, "")
        if wallet not in candidate_wallets:
            continue

        if order.source_side == "BUY":
            stats[wallet]["buy_value"] += max(
                0.0,
                safe_float(order.requested_value_sol),
            )
            continue

        pnl = safe_float(order.realized_pnl_sol)
        stats[wallet]["pnl"] += pnl
        stats[wallet]["closed"] += 1
        if pnl > PNL_EPSILON:
            stats[wallet]["wins"] += 1
        elif pnl < -PNL_EPSILON:
            stats[wallet]["losses"] += 1

    calculated_at = utc_now()
    calculated_rows: list[LiveWalletScore] = []
    minimum_sample = max(1, int(config.min_wallet_closed_trades or 1))

    for wallet in sorted(candidate_wallets):
        profile = profile_map.get(wallet)
        discovered = activity_map.get(wallet)
        wallet_stats = stats[wallet]
        closed = int(wallet_stats["closed"])
        wins = int(wallet_stats["wins"])
        win_rate = round(wins / closed * 100, 4) if closed else 0.0
        roi = (
            round(wallet_stats["pnl"] / wallet_stats["buy_value"] * 100, 4)
            if wallet_stats["buy_value"] > 0
            else 0.0
        )
        profile_score = clamp(safe_float(profile.smart_score) if profile else 0.0)
        live_score = normalize_performance_score(
            win_rate_percent=win_rate,
            roi_percent=roi,
            realized_pnl_sol=wallet_stats["pnl"],
            closed_trades=closed,
        )

        if profile is not None and closed > 0:
            performance_score = profile_score * 0.60 + live_score * 0.40
        elif profile is not None:
            performance_score = profile_score
        elif closed > 0:
            performance_score = live_score
        else:
            performance_score = 0.0

        activity_score = clamp(
            safe_float(discovered.activity_score) if discovered else 0.0
        )
        quality_score = clamp(
            safe_float(discovered.quality_score) if discovered else 0.0
        )
        smart_score = (
            performance_score * 0.65
            + activity_score * 0.15
            + quality_score * 0.20
            if discovered is not None
            else performance_score
        )

        reasons: list[str] = []
        if profile is None:
            reasons.append("PROFILE_NOT_AVAILABLE")
        if closed == 0:
            reasons.append("NO_LIVE_SAMPLE")
        elif closed < minimum_sample:
            reasons.append("LIMITED_LIVE_SAMPLE")
        if smart_score < config.min_wallet_smart_score:
            reasons.append("SMART_SCORE_BELOW_MINIMUM")
        reasons.extend(_activity_reasons(discovered))
        reasons.extend(_quality_reasons(discovered))
        reasons.extend(_promotion_reasons(discovered))
        reasons = list(dict.fromkeys(reasons))

        row = (
            db.query(LiveWalletScore)
            .filter(LiveWalletScore.wallet_address == wallet)
            .first()
        )
        if row is None:
            row = LiveWalletScore(wallet_address=wallet)
            db.add(row)

        row.smart_score = round(clamp(smart_score), 4)
        row.profile_score = round(profile_score, 4)
        row.live_performance_score = round(live_score, 4)
        row.activity_score = round(activity_score, 4)
        row.activity_classification = (
            discovered.activity_classification if discovered else "NON_ANALIZZATO"
        )
        row.quality_score = round(quality_score, 4)
        row.quality_classification = (
            discovered.quality_classification if discovered else "NON_ANALIZZATO"
        )
        row.quality_eligible = bool(discovered.quality_eligible) if discovered else False
        row.promotion_status = (
            discovered.promotion_status if discovered else "NON_ANALIZZATO"
        )
        row.promotion_eligible = (
            bool(discovered.promotion_eligible) if discovered else False
        )
        row.backtest_score = safe_float(discovered.backtest_score if discovered else 0)
        row.backtest_total_return_percent = safe_float(
            discovered.backtest_total_return_percent if discovered else 0
        )
        row.backtest_profit_factor = (
            discovered.backtest_profit_factor if discovered else None
        )
        row.backtest_max_drawdown_percent = safe_float(
            discovered.backtest_max_drawdown_percent if discovered else 0
        )
        row.backtest_jupiter_status = (
            discovered.backtest_jupiter_status if discovered else "NOT_CHECKED"
        )
        row.last_swap_at = discovered.last_swap_at if discovered else None
        row.swaps_24h = int(discovered.swaps_24h if discovered else 0)
        row.swaps_7d = int(discovered.swaps_7d if discovered else 0)
        row.buys_7d = int(discovered.buys_7d if discovered else 0)
        row.sells_7d = int(discovered.sells_7d if discovered else 0)
        row.volume_7d_sol = safe_float(discovered.volume_7d_sol if discovered else 0)
        row.active_days_7d = int(discovered.active_days_7d if discovered else 0)
        row.average_swaps_per_active_day_7d = safe_float(
            discovered.average_swaps_per_active_day_7d if discovered else 0
        )
        row.average_minutes_between_swaps_7d = (
            discovered.average_minutes_between_swaps_7d if discovered else None
        )
        row.win_rate_percent = win_rate
        row.roi_percent = roi
        row.realized_pnl_sol = round(wallet_stats["pnl"], 8)
        row.closed_trades = closed
        row.eligible = (
            discovered is not None
            and bool(discovered.activity_eligible)
            and bool(discovered.quality_eligible)
            and bool(discovered.promotion_eligible)
            and smart_score >= config.min_wallet_smart_score
            and closed >= minimum_sample
        )
        row.reasons = reasons
        row.calculated_at = calculated_at
        calculated_rows.append(row)

    calculated_rows.sort(
        key=lambda item: (
            bool(item.eligible),
            item.smart_score,
            item.realized_pnl_sol,
            item.wallet_address,
        ),
        reverse=True,
    )

    for rank, row in enumerate(calculated_rows, start=1):
        row.rank = rank
        if rank > config.max_source_wallets:
            row.eligible = False
            row.reasons = list(
                dict.fromkeys([*(row.reasons or []), "OUTSIDE_WALLET_LIMIT"])
            )

    record_live_event(
        db,
        event_type="WALLET_RANKING_REFRESHED",
        message="Ranking wallet aggiornato con attività recente e performance.",
        payload={
            "wallets_scored": len(calculated_rows),
            "wallets_returned": min(len(calculated_rows), MAX_RANKING_ROWS),
            "eligible_wallets": sum(1 for row in calculated_rows if row.eligible),
            "minimum_score": config.min_wallet_smart_score,
            "minimum_closed_trades": minimum_sample,
            "activity_filter_enabled": True,
            "quality_filter_enabled": True,
            "promotion_filter_enabled": True,
            "promoted_wallets": sum(
                1 for row in calculated_rows if row.promotion_status == "PROMOSSO"
            ),
            "copyable_wallets": sum(
                1
                for row in calculated_rows
                if row.quality_classification == "COPIABILE"
            ),
            "suspicious_wallets": sum(
                1
                for row in calculated_rows
                if row.quality_classification == "SOSPETTO"
            ),
            "inactive_wallets": sum(
                1
                for row in calculated_rows
                if row.activity_classification == "INATTIVO"
            ),
            "hyperactive_wallets": sum(
                1
                for row in calculated_rows
                if row.activity_classification == "IPERATTIVO"
            ),
        },
    )

    db.commit()
    for row in calculated_rows:
        db.refresh(row)
    return calculated_rows[:MAX_RANKING_ROWS]


def list_live_wallet_ranking(
    db: Session,
    *,
    refresh: bool = False,
) -> list[LiveWalletScore]:
    if refresh or db.query(LiveWalletScore).count() == 0:
        return refresh_live_wallet_ranking(db)

    return (
        db.query(LiveWalletScore)
        .order_by(LiveWalletScore.rank.asc(), LiveWalletScore.smart_score.desc())
        .limit(MAX_RANKING_ROWS)
        .all()
    )


def apply_ranked_wallets(
    db: Session,
    *,
    confirmation: str,
    limit: int | None = None,
) -> dict:
    if confirmation != "APPLY SMART WALLETS":
        raise LiveTradingError(
            "Conferma non valida. Usa esattamente APPLY SMART WALLETS.",
            code="SMART_WALLET_CONFIRMATION_REQUIRED",
            status_code=422,
        )

    config = get_or_create_platform_config(db)
    if not config.auto_wallet_selection_enabled:
        raise LiveTradingError(
            "Abilita prima la selezione wallet automatica nella configurazione.",
            code="AUTO_WALLET_SELECTION_DISABLED",
            status_code=409,
        )

    policy = get_or_create_live_policy(db)
    ranking = refresh_live_wallet_ranking(db)
    resolved_limit = min(max(1, int(limit or config.max_source_wallets)), 50)

    selected = [row.wallet_address for row in ranking if row.eligible][:resolved_limit]
    if not selected:
        raise LiveTradingError(
            "Nessun wallet supera insieme attività, qualità, Smart Score e campione minimo di trade chiusi.",
            code="NO_ELIGIBLE_SOURCE_WALLETS",
            status_code=409,
        )

    policy.source_wallets = selected
    record_live_event(
        db,
        event_type="SMART_WALLETS_APPLIED",
        message="Wallet sorgente aggiornati dal ranking automatico.",
        generation=(policy.dry_run_generation if policy.mode == "DRY_RUN" else None),
        payload={
            "selected_count": len(selected),
            "wallets": selected,
            "minimum_closed_trades": config.min_wallet_closed_trades,
            "activity_filter_enabled": True,
            "quality_filter_enabled": True,
        },
    )
    db.commit()
    db.refresh(policy)

    return {
        "selected_count": len(selected),
        "source_wallets": selected,
        "policy": policy,
    }
