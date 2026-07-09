from collections import defaultdict

from sqlalchemy.orm import Session

from backend.app.models.trade import Trade
from backend.app.models.wallet_profile import WalletProfile


def get_token_signals(
    db: Session,
    min_buyers: int = 1,
):
    buys = (
        db.query(Trade)
        .filter(Trade.side == "BUY")
        .filter(Trade.token_mint.isnot(None))
        .all()
    )

    profiles = {
        profile.wallet_address: profile
        for profile in db.query(WalletProfile).all()
    }

    grouped = defaultdict(list)

    for trade in buys:
        grouped[trade.token_mint].append(trade)

    signals = []

    for token, trades in grouped.items():

        wallets = {}

        for trade in trades:
            wallets[trade.wallet_address] = trade

        total_volume = sum(
            trade.sol_amount or 0
            for trade in trades
        )

        leader_wallet = None
        leader_score = -1

        smart_sum = 0
        roi_sum = 0
        prediction_sum = 0
        conviction_sum = 0

        valid_profiles = 0

        for wallet in wallets:

            profile = profiles.get(wallet)

            if profile is None:
                continue

            # Considera solo wallet realmente smart
            if profile.smart_score < 60:
                continue

            valid_profiles += 1

            smart_sum += profile.smart_score
            roi_sum += profile.roi
            prediction_sum += profile.prediction_score
            conviction_sum += profile.conviction_score

            if profile.smart_score > leader_score:
                leader_score = profile.smart_score
                leader_wallet = wallet

        # Servono almeno N smart wallet
        if valid_profiles < min_buyers:
            continue

        avg_smart = smart_sum / valid_profiles
        avg_roi = roi_sum / valid_profiles
        avg_prediction = prediction_sum / valid_profiles
        avg_conviction = conviction_sum / valid_profiles

        buyers_score = min(valid_profiles * 10, 100)

        positive_roi = max(avg_roi, 0)

        signal_score = (
            avg_smart * 0.50
            + avg_prediction * 0.20
            + avg_conviction * 0.15
            + positive_roi * 0.10
            + buyers_score * 0.05
        )

        if signal_score >= 80:
            confidence = "HIGH"
        elif signal_score >= 65:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        signals.append(
            {
                "token_mint": token,
                "buyers": valid_profiles,
                "leader_wallet": leader_wallet,
                "average_smart_score": round(avg_smart, 2),
                "average_roi": round(avg_roi, 2),
                "signal_score": round(signal_score, 2),
                "confidence": confidence,
                "total_volume_sol": round(total_volume, 4),
            }
        )

    signals.sort(
        key=lambda item: (
            item["signal_score"],
            item["average_smart_score"],
            item["buyers"],
        ),
        reverse=True,
    )

    return {
        "signals": signals,
    } 