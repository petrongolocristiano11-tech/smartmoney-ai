from backend.app.services.early_buyer_engine import calculate_early_buyer_score
from backend.app.services.influence_engine import calculate_wallet_influence
from backend.app.services.wallet_analytics_engine import calculate_wallet_analytics


SMART_SCORE_V22_WEIGHTS = {
    "roi": 0.16,
    "win_rate": 0.16,
    "profit": 0.10,
    "activity": 0.07,
    "avg_trade_size": 0.06,
    "profit_per_token": 0.09,
    "early_buyer": 0.16,
    "influence": 0.12,
    "buy_sell_balance": 0.04,
    "risk": 0.04,
}


def clamp(value: float, minimum: float = 0, maximum: float = 100):
    return max(minimum, min(value, maximum))


def calculate_risk_score(risk_level: str):
    if risk_level == "LOW":
        return 100

    if risk_level == "MEDIUM":
        return 50

    return 0


def calculate_buy_sell_balance_score(buy_sell_ratio: float):
    if buy_sell_ratio <= 0:
        return 0

    distance_from_balance = abs(1 - buy_sell_ratio)

    return clamp(100 - distance_from_balance * 50)


def calculate_smart_score(db, wallet_address: str):
    analytics = calculate_wallet_analytics(db, wallet_address)
    early_buyer = calculate_early_buyer_score(db, wallet_address)
    influence = calculate_wallet_influence(db, wallet_address)

    roi_score = clamp((analytics["total_roi_percent"] + 100) / 2)
    win_rate_score = clamp(analytics["win_rate_percent"])
    profit_score = clamp(analytics["total_profit_loss_sol"] * 10 + 50)
    activity_score = clamp(analytics["reliable_positions"] * 2)
    avg_trade_size_score = clamp(analytics["average_trade_size_sol"] * 100)
    profit_per_token_score = clamp(analytics["profit_per_token"] * 100 + 50)
    early_buyer_score = clamp(early_buyer["early_buyer_score"])
    influence_score = clamp(influence["influence_score"])
    buy_sell_balance_score = calculate_buy_sell_balance_score(
        analytics["buy_sell_ratio"]
    )
    risk_score = calculate_risk_score(analytics["risk_level"])

    smart_score = (
        roi_score * SMART_SCORE_V22_WEIGHTS["roi"]
        + win_rate_score * SMART_SCORE_V22_WEIGHTS["win_rate"]
        + profit_score * SMART_SCORE_V22_WEIGHTS["profit"]
        + activity_score * SMART_SCORE_V22_WEIGHTS["activity"]
        + avg_trade_size_score * SMART_SCORE_V22_WEIGHTS["avg_trade_size"]
        + profit_per_token_score * SMART_SCORE_V22_WEIGHTS["profit_per_token"]
        + early_buyer_score * SMART_SCORE_V22_WEIGHTS["early_buyer"]
        + influence_score * SMART_SCORE_V22_WEIGHTS["influence"]
        + buy_sell_balance_score * SMART_SCORE_V22_WEIGHTS["buy_sell_balance"]
        + risk_score * SMART_SCORE_V22_WEIGHTS["risk"]
    )

    return {
        "wallet": wallet_address,
        "smart_score": round(smart_score, 2),
        "version": "2.2",
        "components": {
            "roi_score": round(roi_score, 2),
            "win_rate_score": round(win_rate_score, 2),
            "profit_score": round(profit_score, 2),
            "activity_score": round(activity_score, 2),
            "avg_trade_size_score": round(avg_trade_size_score, 2),
            "profit_per_token_score": round(profit_per_token_score, 2),
            "early_buyer_score": round(early_buyer_score, 2),
            "influence_score": round(influence_score, 2),
            "buy_sell_balance_score": round(buy_sell_balance_score, 2),
            "risk_score": round(risk_score, 2),
        },
        "weights": SMART_SCORE_V22_WEIGHTS,
        "analytics": analytics,
        "early_buyer": early_buyer,
        "influence": influence,
    } 