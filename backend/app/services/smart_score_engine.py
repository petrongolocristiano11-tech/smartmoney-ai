from backend.app.core.constants import SMART_SCORE_WEIGHTS
from backend.app.services.wallet_analytics_engine import calculate_wallet_analytics


def clamp(value: float, minimum: float = 0, maximum: float = 100):
    return max(minimum, min(value, maximum))


def calculate_smart_score(db, wallet_address: str):
    analytics = calculate_wallet_analytics(db, wallet_address)

    roi_score = clamp((analytics["total_roi_percent"] + 100) / 2)
    win_rate_score = clamp(analytics["win_rate_percent"])
    profit_score = clamp(analytics["total_profit_loss_sol"] * 10 + 50)
    activity_score = clamp(analytics["reliable_positions"])

    smart_score = (
        roi_score * SMART_SCORE_WEIGHTS["roi"]
        + win_rate_score * SMART_SCORE_WEIGHTS["win_rate"]
        + profit_score * SMART_SCORE_WEIGHTS["profit"]
        + activity_score * SMART_SCORE_WEIGHTS["activity"]
    )

    return {
        "wallet": wallet_address,
        "smart_score": round(smart_score, 2),
        "components": {
            "roi_score": round(roi_score, 2),
            "win_rate_score": round(win_rate_score, 2),
            "profit_score": round(profit_score, 2),
            "activity_score": round(activity_score, 2),
        },
        "weights": SMART_SCORE_WEIGHTS,
        "analytics": analytics,
    } 