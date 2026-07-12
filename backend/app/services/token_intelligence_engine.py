from collections import defaultdict
from datetime import datetime
from math import ceil

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.models.token import Token
from backend.app.models.trade import Trade
from backend.app.models.wallet_profile import WalletProfile


def _as_float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _iso_datetime(value):
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.isoformat()

    if hasattr(value, "isoformat"):
        return value.isoformat()

    return str(value)


def _split_traits(value):
    if not value:
        return []

    return [
        trait.strip()
        for trait in str(value).split(",")
        if trait.strip()
    ]


def _sample_timeline(points, maximum_points=250):
    if len(points) <= maximum_points:
        return points

    step = ceil(len(points) / maximum_points)
    sampled = points[::step]

    if sampled[-1] != points[-1]:
        sampled.append(points[-1])

    return sampled


def calculate_token_intelligence(
    db: Session,
    token_mint: str,
):
    trades = (
        db.query(Trade)
        .filter(Trade.token_mint == token_mint)
        .order_by(Trade.id.asc())
        .all()
    )

    if not trades:
        return None

    wallet_addresses = {
        trade.wallet_address
        for trade in trades
        if trade.wallet_address
    }

    profiles = {
        profile.wallet_address: profile
        for profile in (
            db.query(WalletProfile)
            .filter(
                WalletProfile.wallet_address.in_(
                    wallet_addresses
                )
            )
            .all()
        )
    }

    wallet_activity = defaultdict(
        lambda: {
            "trades": 0,
            "buys": 0,
            "sells": 0,
            "buy_volume_sol": 0.0,
            "sell_volume_sol": 0.0,
            "token_bought": 0.0,
            "token_sold": 0.0,
            "first_seen": None,
            "last_seen": None,
        }
    )

    total_buy_volume = 0.0
    total_sell_volume = 0.0
    total_token_bought = 0.0
    total_token_sold = 0.0

    buy_trades = 0
    sell_trades = 0

    buyer_wallets = set()
    seller_wallets = set()

    timeline = []
    cumulative_net_buy_sol = 0.0

    for trade in trades:
        side = (trade.side or "UNKNOWN").upper()
        sol_amount = _as_float(trade.sol_amount)
        token_amount = _as_float(trade.token_amount)
        timestamp = trade.block_time or trade.created_at
        wallet_address = trade.wallet_address

        activity = wallet_activity[wallet_address]
        activity["trades"] += 1

        if activity["first_seen"] is None:
            activity["first_seen"] = timestamp

        activity["last_seen"] = timestamp

        if side == "BUY":
            buy_trades += 1
            buyer_wallets.add(wallet_address)

            total_buy_volume += sol_amount
            total_token_bought += token_amount
            cumulative_net_buy_sol += sol_amount

            activity["buys"] += 1
            activity["buy_volume_sol"] += sol_amount
            activity["token_bought"] += token_amount

        elif side == "SELL":
            sell_trades += 1
            seller_wallets.add(wallet_address)

            total_sell_volume += sol_amount
            total_token_sold += token_amount
            cumulative_net_buy_sol -= sol_amount

            activity["sells"] += 1
            activity["sell_volume_sol"] += sol_amount
            activity["token_sold"] += token_amount

        timeline.append(
            {
                "trade_id": trade.id,
                "timestamp": _iso_datetime(timestamp),
                "side": side,
                "wallet": wallet_address,
                "sol_amount": round(sol_amount, 6),
                "cumulative_net_buy_sol": round(
                    cumulative_net_buy_sol,
                    6,
                ),
            }
        )

    wallet_rows = []
    smart_profiles = []

    for wallet_address, activity in wallet_activity.items():
        profile = profiles.get(wallet_address)

        smart_score = _as_float(
            profile.smart_score if profile else 0
        )

        is_smart = smart_score >= 60

        if is_smart and profile is not None:
            smart_profiles.append(profile)

        net_buy_volume = (
            activity["buy_volume_sol"]
            - activity["sell_volume_sol"]
        )

        wallet_rows.append(
            {
                "wallet": wallet_address,
                "is_smart": is_smart,
                "smart_score": round(smart_score, 2),
                "classification": (
                    profile.classification
                    if profile
                    else "UNRANKED"
                ),
                "traits": _split_traits(
                    profile.traits if profile else None
                ),
                "roi_percent": round(
                    _as_float(
                        profile.roi if profile else 0
                    ),
                    2,
                ),
                "win_rate_percent": round(
                    _as_float(
                        profile.win_rate if profile else 0
                    ),
                    2,
                ),
                "profit_loss_sol": round(
                    _as_float(
                        profile.profit if profile else 0
                    ),
                    4,
                ),
                "trades": activity["trades"],
                "buys": activity["buys"],
                "sells": activity["sells"],
                "buy_volume_sol": round(
                    activity["buy_volume_sol"],
                    6,
                ),
                "sell_volume_sol": round(
                    activity["sell_volume_sol"],
                    6,
                ),
                "net_buy_volume_sol": round(
                    net_buy_volume,
                    6,
                ),
                "token_bought": round(
                    activity["token_bought"],
                    6,
                ),
                "token_sold": round(
                    activity["token_sold"],
                    6,
                ),
                "first_seen": _iso_datetime(
                    activity["first_seen"]
                ),
                "last_seen": _iso_datetime(
                    activity["last_seen"]
                ),
            }
        )

    wallet_rows.sort(
        key=lambda item: (
            item["is_smart"],
            item["smart_score"],
            item["net_buy_volume_sol"],
            item["buy_volume_sol"],
        ),
        reverse=True,
    )

    smart_wallet_count = len(smart_profiles)

    average_smart_score = (
        sum(
            _as_float(profile.smart_score)
            for profile in smart_profiles
        )
        / smart_wallet_count
        if smart_wallet_count
        else 0
    )

    average_roi = (
        sum(
            _as_float(profile.roi)
            for profile in smart_profiles
        )
        / smart_wallet_count
        if smart_wallet_count
        else 0
    )

    total_volume = (
        total_buy_volume + total_sell_volume
    )

    buy_pressure_percent = (
        total_buy_volume / total_volume * 100
        if total_volume > 0
        else 0
    )

    smart_wallet_component = min(
        smart_wallet_count * 12,
        100,
    )

    activity_component = min(
        len(trades) * 2,
        100,
    )

    positive_roi_component = min(
        max(average_roi, 0),
        100,
    )

    token_score = min(
        100,
        average_smart_score * 0.45
        + smart_wallet_component * 0.20
        + buy_pressure_percent * 0.15
        + positive_roi_component * 0.10
        + activity_component * 0.10,
    )

    if token_score >= 80:
        confidence = "HIGH"
    elif token_score >= 65:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    recent_trades = []

    for trade in reversed(trades[-100:]):
        recent_trades.append(
            {
                "id": trade.id,
                "signature": trade.signature,
                "wallet": trade.wallet_address,
                "side": trade.side,
                "source": trade.source,
                "token_amount": round(
                    _as_float(trade.token_amount),
                    6,
                ),
                "sol_amount": round(
                    _as_float(trade.sol_amount),
                    6,
                ),
                "success": trade.success,
                "timestamp": _iso_datetime(
                    trade.block_time
                    or trade.created_at
                ),
            }
        )

    token_record = None

    try:
        token_record = (
            db.query(Token)
            .filter(Token.address == token_mint)
            .first()
        )
    except SQLAlchemyError:
        db.rollback()

    return {
        "token": {
            "mint": token_mint,
            "symbol": (
                token_record.symbol
                if token_record
                else None
            ),
            "name": (
                token_record.name
                if token_record
                else None
            ),
        },
        "score": {
            "token_score": round(token_score, 2),
            "confidence": confidence,
            "average_smart_score": round(
                average_smart_score,
                2,
            ),
            "average_smart_roi": round(
                average_roi,
                2,
            ),
            "buy_pressure_percent": round(
                buy_pressure_percent,
                2,
            ),
        },
        "stats": {
            "total_trades": len(trades),
            "buy_trades": buy_trades,
            "sell_trades": sell_trades,
            "unique_wallets": len(wallet_activity),
            "unique_buyers": len(buyer_wallets),
            "unique_sellers": len(seller_wallets),
            "smart_wallets": smart_wallet_count,
            "total_volume_sol": round(
                total_volume,
                6,
            ),
            "buy_volume_sol": round(
                total_buy_volume,
                6,
            ),
            "sell_volume_sol": round(
                total_sell_volume,
                6,
            ),
            "net_buy_volume_sol": round(
                total_buy_volume
                - total_sell_volume,
                6,
            ),
            "total_token_bought": round(
                total_token_bought,
                6,
            ),
            "total_token_sold": round(
                total_token_sold,
                6,
            ),
            "first_trade_at": _iso_datetime(
                trades[0].block_time
                or trades[0].created_at
            ),
            "last_trade_at": _iso_datetime(
                trades[-1].block_time
                or trades[-1].created_at
            ),
        },
        "wallets": wallet_rows[:150],
        "timeline": _sample_timeline(timeline),
        "recent_trades": recent_trades,
    } 