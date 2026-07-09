from backend.app.services.wallet_analytics_engine import calculate_wallet_analytics
from backend.app.services.early_buyer_engine import calculate_early_buyer_score
from backend.app.services.influence_engine import calculate_wallet_influence
from backend.app.services.conviction_engine import calculate_wallet_conviction


def calculate_wallet_dna(db, wallet_address: str):

    analytics = calculate_wallet_analytics(db, wallet_address)
    early = calculate_early_buyer_score(db, wallet_address)
    influence = calculate_wallet_influence(db, wallet_address)
    conviction = calculate_wallet_conviction(db, wallet_address)

    traits = []

    if early["early_buyer_score"] >= 70:
        traits.append("SNIPER")

    if influence["influence_score"] >= 70:
        traits.append("LEADER")

    if conviction["conviction_score"] >= 70:
        traits.append("CONVICTION")

    if analytics["risk_level"] == "LOW":
        traits.append("LOW_RISK")

    if analytics["win_rate_percent"] >= 70:
        traits.append("CONSISTENT")

    if analytics["total_roi_percent"] >= 50:
        traits.append("HIGH_ROI")

    if analytics["average_trade_size_sol"] >= 1:
        traits.append("WHALE")

    if analytics["buy_sell_ratio"] > 1.5:
        traits.append("ACCUMULATOR")

    if analytics["buy_sell_ratio"] < 0.7:
        traits.append("FAST_EXIT")

    return {
        "wallet": wallet_address,
        "traits": traits,
        "dna_score": len(traits) * 10,
        "classification": traits[0] if traits else "NORMAL",
    } 