from sqlalchemy.orm import Session

from backend.app.services.portfolio_engine import build_wallet_portfolio
from backend.app.services.roi_engine import calculate_wallet_roi
from backend.app.services.win_rate_engine import calculate_wallet_win_rate
from backend.app.services.wallet_analytics_engine import (
    calculate_wallet_analytics,
)
from backend.app.services.smart_score_engine import (
    calculate_smart_score,
)


def analyze_wallet(
    db: Session,
    wallet_address: str,
):
    """
    Analisi completa di un wallet.
    """

    portfolio = build_wallet_portfolio(
        db,
        wallet_address,
    )

    roi = calculate_wallet_roi(
        db,
        wallet_address,
    )

    win_rate = calculate_wallet_win_rate(
        db,
        wallet_address,
    )

    analytics = calculate_wallet_analytics(
        db,
        wallet_address,
    )

    smart_score = calculate_smart_score(
        db,
        wallet_address,
    )

    return {
        "wallet": wallet_address,
        "portfolio": portfolio,
        "roi": roi,
        "win_rate": win_rate,
        "analytics": analytics,
        "smart_score": smart_score,
    } 