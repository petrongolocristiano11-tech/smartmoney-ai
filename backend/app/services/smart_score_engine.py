from backend.app.services.wallet_analytics_engine import calculate_wallet_analytics


SMART_SCORE_V2_WEIGHTS = {
    "roi": 0.25,
    "win_rate": 0.25,
    "profit": 0.15,
    "activity": 0.10,
    "avg_trade_size": 0.10,
    "profit_per_token": 0.10,
    "risk": 0.05,
}


def clamp(value: float, minimum: float = 0, maximum: float = 100):
    return max(minimum, min(value, maximum))


def calculate_risk_score(risk_level: str):
    if risk_level == "LOW":
        return 100

    if risk_level == "MEDIUM":
        return 50

    return 0


def calculate_smart_score(db, wallet_address: str):
    analytics = calculate_wallet_analytics(db, wallet_address)

    roi_score = clamp((analytics["total_roi_percent"] + 100) / 2)
    win_rate_score = clamp(analytics["win_rate_percent"])
    profit_score = clamp(analytics["total_profit_loss_sol"] * 10 + 50)
    activity_score = clamp(analytics["reliable_positions"] * 2)
    avg_trade_size_score = clamp(analytics["average_trade_size_sol"] * 100)
    profit_per_token_score = clamp(analytics["profit_per_token"] * 100 + 50)
    risk_score = calculate_risk_score(analytics["risk_level"])

    smart_score = (
        roi_score * SMART_SCORE_V2_WEIGHTS["roi"]
        + win_rate_score * SMART_SCORE_V2_WEIGHTS["win_rate"]
        + profit_score * SMART_SCORE_V2_WEIGHTS["profit"]
        + activity_score * SMART_SCORE_V2_WEIGHTS["activity"]
        + avg_trade_size_score * SMART_SCORE_V2_WEIGHTS["avg_trade_size"]
        + profit_per_token_score * SMART_SCORE_V2_WEIGHTS["profit_per_token"]
        + risk_score * SMART_SCORE_V2_WEIGHTS["risk"]
    )

    return {
        "wallet": wallet_address,
        "smart_score": round(smart_score, 2),
        "version": "2.0",
        "components": {
            "roi_score": round(roi_score, 2),
            "win_rate_score": round(win_rate_score, 2),
            "profit_score": round(profit_score, 2),
            "activity_score": round(activity_score, 2),
            "avg_trade_size_score": round(avg_trade_size_score, 2),
            "profit_per_token_score": round(profit_per_token_score, 2),
            "risk_score": round(risk_score, 2),
        },
        "weights": SMART_SCORE_V2_WEIGHTS,
        "analytics": analytics,
    } 