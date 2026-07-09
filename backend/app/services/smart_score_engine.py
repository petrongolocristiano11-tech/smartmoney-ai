from backend.app.services.wallet_dna_engine import calculate_wallet_dna


SMART_SCORE_V3_WEIGHTS = {
    "performance": 0.30,
    "timing": 0.20,
    "leadership": 0.15,
    "conviction": 0.10,
    "holding": 0.10,
    "prediction": 0.10,
    "risk": 0.05,
}


def clamp(value, minimum=0, maximum=100):
    return max(minimum, min(value, maximum))


def risk_score(risk_level):
    if risk_level == "LOW":
        return 100
    if risk_level == "MEDIUM":
        return 50
    return 0


def calculate_smart_score(db, wallet_address: str):
    dna = calculate_wallet_dna(db, wallet_address)

    analytics = dna["analytics"]
    early = dna["early_buyer"]
    influence = dna["influence"]
    conviction = dna["conviction"]
    holding = dna["holding"]
    prediction = dna["prediction"]

    performance_score = clamp(
        analytics["win_rate_percent"] * 0.4
        + ((analytics["total_roi_percent"] + 100) / 2) * 0.3
        + (analytics["profit_per_token"] * 100 + 50) * 0.3
    )

    timing_score = clamp(early["early_buyer_score"])
    leadership_score = clamp(influence["influence_score"])
    conviction_score = clamp(conviction["conviction_score"])
    holding_score = clamp(holding["holding_score"])
    prediction_score = clamp(prediction["prediction_score"])
    wallet_risk_score = risk_score(analytics["risk_level"])

    smart_score = (
        performance_score * SMART_SCORE_V3_WEIGHTS["performance"]
        + timing_score * SMART_SCORE_V3_WEIGHTS["timing"]
        + leadership_score * SMART_SCORE_V3_WEIGHTS["leadership"]
        + conviction_score * SMART_SCORE_V3_WEIGHTS["conviction"]
        + holding_score * SMART_SCORE_V3_WEIGHTS["holding"]
        + prediction_score * SMART_SCORE_V3_WEIGHTS["prediction"]
        + wallet_risk_score * SMART_SCORE_V3_WEIGHTS["risk"]
    )

    return {
        "wallet": wallet_address,
        "smart_score": round(smart_score, 2),
        "version": "3.0",
        "components": {
            "performance_score": round(performance_score, 2),
            "timing_score": round(timing_score, 2),
            "leadership_score": round(leadership_score, 2),
            "conviction_score": round(conviction_score, 2),
            "holding_score": round(holding_score, 2),
            "prediction_score": round(prediction_score, 2),
            "risk_score": round(wallet_risk_score, 2),
        },
        "weights": SMART_SCORE_V3_WEIGHTS,
        "dna": dna,
    } 