from sqlalchemy.orm import Session

from backend.app.models.trade import Trade
from backend.app.models.wallet_profile import WalletProfile
from backend.app.services.alert_engine import get_alerts
from backend.app.services.signals_engine import get_token_signals


def get_dashboard(db: Session):
    wallets = db.query(WalletProfile).count()

    trades = db.query(Trade).count()

    smart_wallets = (
        db.query(WalletProfile)
        .filter(WalletProfile.smart_score >= 60)
        .count()
    )

    top_wallets = (
        db.query(WalletProfile)
        .order_by(WalletProfile.smart_score.desc())
        .limit(5)
        .all()
    )

    signals = get_token_signals(
        db,
        min_buyers=2,
    )["signals"][:5]

    alerts = get_alerts(
        db,
        min_signal_score=50,
    )["alerts"][:5]

    return {
        "stats": {
            "wallets": wallets,
            "smart_wallets": smart_wallets,
            "trades": trades,
            "signals": len(signals),
            "alerts": len(alerts),
        },
        "top_wallets": [
            {
                "wallet": w.wallet_address,
                "smart_score": w.smart_score,
                "roi": w.roi,
                "win_rate": w.win_rate,
                "classification": w.classification,
            }
            for w in top_wallets
        ],
        "top_signals": signals,
        "latest_alerts": alerts,
    } 