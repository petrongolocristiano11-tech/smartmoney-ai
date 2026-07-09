from backend.app.services.conviction_engine import calculate_wallet_conviction
from backend.app.services.early_buyer_engine import calculate_early_buyer_score
from backend.app.services.holding_time_engine import calculate_wallet_holding_time
from backend.app.services.influence_engine import calculate_wallet_influence
from backend.app.services.prediction_engine import calculate_wallet_prediction
from backend.app.services.wallet_analytics_engine import calculate_wallet_analytics


def calculate_wallet_dna(db, wallet_address: str):
    analytics = calculate_wallet_analytics(db, wallet_address)
    early = calculate_early_buyer_score(db, wallet_address)
    influence = calculate_wallet_influence(db, wallet_address)
    conviction = calculate_wallet_conviction(db, wallet_address)
    holding = calculate_wallet_holding_time(db, wallet_address)
    prediction = calculate_wallet_prediction(db, wallet_address)

    traits = []

    if early["early_buyer_score"] >= 70:
        traits.append("SNIPER")

    if influence["influence_score"] >= 70:
        traits.append("LEADER")

    if conviction["conviction_score"] >= 70:
        traits.append("HIGH_CONVICTION")

    if holding["style"] in ["SWING", "HOLDER"]:
        traits.append(holding["style"])

    if analytics["risk_level"] == "LOW":
        traits.append("LOW_RISK")

    if analytics["win_rate_percent"] >= 70:
        traits.append("CONSISTENT")

    if prediction["prediction_score"] >= 70:
        traits.append("GOOD_SELECTOR")

    if analytics["average_trade_size_sol"] >= 1:
        traits.append("WHALE")

    if not traits:
        traits.append("NORMAL")

    dna_score = min(100, len(traits) * 12)

    return {
        "wallet": wallet_address,
        "classification": traits[0],
        "traits": traits,
        "dna_score": dna_score,
        "analytics": analytics,
        "early_buyer": early,
        "influence": influence,
        "conviction": conviction,
        "holding": holding,
        "prediction": prediction,
    } 