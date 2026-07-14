from math import tanh
from typing import Any

from backend.app.services.wallet_dna_engine import (
    calculate_wallet_dna,
)


SMART_SCORE_VERSION = "4.0"

NEUTRAL_SCORE = 50.0

SMART_SCORE_V4_WEIGHTS = {
    "performance": 0.30,
    "timing": 0.12,
    "leadership": 0.10,
    "conviction": 0.10,
    "holding": 0.08,
    "prediction": 0.10,
    "risk": 0.08,
    "consistency": 0.07,
    "data_quality": 0.05,
}


def _as_float(
    value: Any,
    default: float = 0.0,
) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(
    value: float,
    minimum: float = 0,
    maximum: float = 100,
) -> float:
    return max(
        minimum,
        min(_as_float(value), maximum),
    )


def normalize_symmetric(
    value: float,
    scale: float,
) -> float:
    """
    Trasforma valori positivi e negativi
    in un punteggio compreso tra 0 e 100.

    Zero corrisponde a 50. La funzione tanh
    evita che valori estremi dominino lo score.
    """

    normalized_scale = abs(
        _as_float(scale)
    )

    if normalized_scale <= 0:
        return NEUTRAL_SCORE

    normalized_value = _as_float(value)

    return clamp(
        NEUTRAL_SCORE
        + NEUTRAL_SCORE
        * tanh(
            normalized_value
            / normalized_scale
        )
    )


def ratio_to_score(
    value: float,
    target: float,
) -> float:
    """
    Restituisce 100 quando il valore raggiunge
    il target. I valori superiori restano a 100.
    """

    normalized_target = _as_float(target)

    if normalized_target <= 0:
        return 0.0

    return clamp(
        _as_float(value)
        / normalized_target
        * 100
    )


def smoothed_success_rate(
    successes: float,
    total: float,
    prior_rate: float = 0.50,
    prior_weight: float = 6.0,
) -> float:
    """
    Media bayesiana semplificata.

    Evita che un wallet con 1 vittoria su 1
    posizione riceva immediatamente un 100%.
    """

    normalized_total = max(
        _as_float(total),
        0,
    )

    normalized_successes = clamp(
        _as_float(successes),
        0,
        normalized_total,
    )

    if normalized_total <= 0:
        return prior_rate * 100

    adjusted_successes = (
        normalized_successes
        + prior_rate * prior_weight
    )

    adjusted_total = (
        normalized_total
        + prior_weight
    )

    return clamp(
        adjusted_successes
        / adjusted_total
        * 100
    )


def calculate_data_quality_score(
    analytics: dict[str, Any],
) -> float:
    total_trades = _as_float(
        analytics.get("total_trades")
    )

    unique_tokens = _as_float(
        analytics.get("unique_tokens")
    )

    reliable_positions = _as_float(
        analytics.get(
            "reliable_positions"
        )
    )

    closed_positions = (
        _as_float(
            analytics.get(
                "winning_positions"
            )
        )
        + _as_float(
            analytics.get(
                "losing_positions"
            )
        )
    )

    trade_depth_score = ratio_to_score(
        total_trades,
        40,
    )

    token_depth_score = ratio_to_score(
        unique_tokens,
        8,
    )

    reliable_depth_score = ratio_to_score(
        reliable_positions,
        10,
    )

    closed_depth_score = ratio_to_score(
        closed_positions,
        10,
    )

    return clamp(
        trade_depth_score * 0.25
        + token_depth_score * 0.25
        + reliable_depth_score * 0.30
        + closed_depth_score * 0.20
    )


def calculate_performance_score(
    analytics: dict[str, Any],
) -> float:
    wins = _as_float(
        analytics.get("winning_positions")
    )

    losses = _as_float(
        analytics.get("losing_positions")
    )

    closed_positions = wins + losses

    smoothed_win_rate = (
        smoothed_success_rate(
            successes=wins,
            total=closed_positions,
        )
    )

    roi_score = normalize_symmetric(
        analytics.get(
            "total_roi_percent",
            0,
        ),
        scale=75,
    )

    profit_per_token_score = (
        normalize_symmetric(
            analytics.get(
                "profit_per_token",
                0,
            ),
            scale=0.25,
        )
    )

    total_profit_score = (
        normalize_symmetric(
            analytics.get(
                "total_profit_loss_sol",
                0,
            ),
            scale=1.0,
        )
    )

    return clamp(
        smoothed_win_rate * 0.35
        + roi_score * 0.30
        + profit_per_token_score * 0.20
        + total_profit_score * 0.15
    )


def calculate_consistency_score(
    analytics: dict[str, Any],
) -> float:
    wins = _as_float(
        analytics.get("winning_positions")
    )

    losses = _as_float(
        analytics.get("losing_positions")
    )

    closed_positions = wins + losses

    roi_percent = _as_float(
        analytics.get(
            "total_roi_percent"
        )
    )

    total_profit = _as_float(
        analytics.get(
            "total_profit_loss_sol"
        )
    )

    adjusted_win_rate = (
        smoothed_success_rate(
            successes=wins,
            total=closed_positions,
        )
    )

    if (
        roi_percent > 0
        and total_profit > 0
    ):
        result_agreement = 100
    elif (
        roi_percent >= 0
        and total_profit >= 0
    ):
        result_agreement = 60
    elif (
        roi_percent < 0
        and total_profit < 0
    ):
        result_agreement = 10
    else:
        result_agreement = 40

    sample_depth = ratio_to_score(
        closed_positions,
        12,
    )

    return clamp(
        adjusted_win_rate * 0.55
        + result_agreement * 0.25
        + sample_depth * 0.20
    )


def calculate_risk_score(
    analytics: dict[str, Any],
) -> float:
    risk_level = str(
        analytics.get(
            "risk_level",
            "MEDIUM",
        )
    ).upper()

    base_scores = {
        "LOW": 90,
        "MEDIUM": 60,
        "HIGH": 25,
    }

    score = base_scores.get(
        risk_level,
        50,
    )

    roi_percent = _as_float(
        analytics.get(
            "total_roi_percent"
        )
    )

    total_profit = _as_float(
        analytics.get(
            "total_profit_loss_sol"
        )
    )

    buy_trades = _as_float(
        analytics.get("buy_trades")
    )

    sell_trades = _as_float(
        analytics.get("sell_trades")
    )

    buy_sell_ratio = _as_float(
        analytics.get("buy_sell_ratio")
    )

    reliable_positions = _as_float(
        analytics.get(
            "reliable_positions"
        )
    )

    if roi_percent < -25:
        score -= 15

    if total_profit < 0:
        score -= 10

    if (
        buy_trades > 0
        and sell_trades == 0
    ):
        score -= 15

    if buy_sell_ratio > 5:
        score -= 10

    if reliable_positions == 0:
        score = min(score, 20)

    return clamp(score)


def calculate_penalties(
    analytics: dict[str, Any],
) -> list[dict[str, Any]]:
    penalties: list[dict[str, Any]] = []

    total_trades = _as_float(
        analytics.get("total_trades")
    )

    unique_tokens = _as_float(
        analytics.get("unique_tokens")
    )

    reliable_positions = _as_float(
        analytics.get(
            "reliable_positions"
        )
    )

    buy_trades = _as_float(
        analytics.get("buy_trades")
    )

    sell_trades = _as_float(
        analytics.get("sell_trades")
    )

    risk_level = str(
        analytics.get(
            "risk_level",
            "MEDIUM",
        )
    ).upper()

    if total_trades < 5:
        penalties.append(
            {
                "code": "LOW_TRADE_SAMPLE",
                "points": 6,
            }
        )

    if reliable_positions == 0:
        penalties.append(
            {
                "code": "NO_RELIABLE_POSITIONS",
                "points": 14,
            }
        )

    if unique_tokens < 2:
        penalties.append(
            {
                "code": "LOW_TOKEN_DIVERSITY",
                "points": 5,
            }
        )

    if (
        buy_trades > 0
        and sell_trades == 0
    ):
        penalties.append(
            {
                "code": "NO_SELL_HISTORY",
                "points": 8,
            }
        )

    if risk_level == "HIGH":
        penalties.append(
            {
                "code": "HIGH_RISK_PROFILE",
                "points": 8,
            }
        )

    return penalties


def get_evidence_level(
    data_quality_score: float,
) -> str:
    if data_quality_score >= 70:
        return "HIGH"

    if data_quality_score >= 35:
        return "MEDIUM"

    return "LOW"


def build_score_reasons(
    components: dict[str, float],
    penalties: list[dict[str, Any]],
) -> list[str]:
    reasons: list[str] = []

    if components["performance_score"] >= 70:
        reasons.append(
            "Performance storica positiva"
        )

    if components["timing_score"] >= 70:
        reasons.append(
            "Buona capacità di ingresso anticipato"
        )

    if components["leadership_score"] >= 70:
        reasons.append(
            "Influenza rilevante su altri wallet"
        )

    if components["prediction_score"] >= 70:
        reasons.append(
            "Buona selezione storica dei token"
        )

    if components["data_quality_score"] < 35:
        reasons.append(
            "Evidenza statistica ancora limitata"
        )

    if components["risk_score"] < 40:
        reasons.append(
            "Profilo di rischio elevato"
        )

    if penalties:
        reasons.append(
            "Applicate penalità per dati incompleti"
        )

    if not reasons:
        reasons.append(
            "Profilo con caratteristiche intermedie"
        )

    return reasons


def calculate_score_from_dna(
    wallet_address: str,
    dna: dict[str, Any],
) -> dict[str, Any]:
    analytics = dna["analytics"]
    early = dna["early_buyer"]
    influence = dna["influence"]
    conviction = dna["conviction"]
    holding = dna["holding"]
    prediction = dna["prediction"]

    performance_score = (
        calculate_performance_score(
            analytics
        )
    )

    timing_score = clamp(
        early.get(
            "early_buyer_score",
            0,
        )
    )

    leadership_score = clamp(
        influence.get(
            "influence_score",
            0,
        )
    )

    conviction_score = clamp(
        conviction.get(
            "conviction_score",
            0,
        )
    )

    holding_score = clamp(
        holding.get(
            "holding_score",
            0,
        )
    )

    prediction_score = clamp(
        prediction.get(
            "prediction_score",
            0,
        )
    )

    wallet_risk_score = (
        calculate_risk_score(
            analytics
        )
    )

    consistency_score = (
        calculate_consistency_score(
            analytics
        )
    )

    data_quality_score = (
        calculate_data_quality_score(
            analytics
        )
    )

    components = {
        "performance_score": (
            performance_score
        ),
        "timing_score": timing_score,
        "leadership_score": (
            leadership_score
        ),
        "conviction_score": (
            conviction_score
        ),
        "holding_score": holding_score,
        "prediction_score": (
            prediction_score
        ),
        "risk_score": (
            wallet_risk_score
        ),
        "consistency_score": (
            consistency_score
        ),
        "data_quality_score": (
            data_quality_score
        ),
    }

    raw_score = (
        performance_score
        * SMART_SCORE_V4_WEIGHTS[
            "performance"
        ]
        + timing_score
        * SMART_SCORE_V4_WEIGHTS[
            "timing"
        ]
        + leadership_score
        * SMART_SCORE_V4_WEIGHTS[
            "leadership"
        ]
        + conviction_score
        * SMART_SCORE_V4_WEIGHTS[
            "conviction"
        ]
        + holding_score
        * SMART_SCORE_V4_WEIGHTS[
            "holding"
        ]
        + prediction_score
        * SMART_SCORE_V4_WEIGHTS[
            "prediction"
        ]
        + wallet_risk_score
        * SMART_SCORE_V4_WEIGHTS[
            "risk"
        ]
        + consistency_score
        * SMART_SCORE_V4_WEIGHTS[
            "consistency"
        ]
        + data_quality_score
        * SMART_SCORE_V4_WEIGHTS[
            "data_quality"
        ]
    )

    confidence_factor = (
        0.35
        + 0.65
        * (
            data_quality_score
            / 100
        )
    )

    confidence_adjusted_score = (
        NEUTRAL_SCORE
        + (
            raw_score
            - NEUTRAL_SCORE
        )
        * confidence_factor
    )

    penalties = calculate_penalties(
        analytics
    )

    penalty_points = sum(
        _as_float(
            penalty.get("points")
        )
        for penalty in penalties
    )

    smart_score = clamp(
        confidence_adjusted_score
        - penalty_points
    )

    rounded_components = {
        key: round(value, 2)
        for key, value
        in components.items()
    }

    return {
        "wallet": wallet_address,
        "smart_score": round(
            smart_score,
            2,
        ),
        "raw_score": round(
            raw_score,
            2,
        ),
        "confidence": round(
            data_quality_score,
            2,
        ),
        "evidence_level": (
            get_evidence_level(
                data_quality_score
            )
        ),
        "penalty_points": round(
            penalty_points,
            2,
        ),
        "penalties": penalties,
        "reasons": build_score_reasons(
            rounded_components,
            penalties,
        ),
        "version": SMART_SCORE_VERSION,
        "components": rounded_components,
        "weights": SMART_SCORE_V4_WEIGHTS,
        "dna": dna,
    }


def calculate_smart_score(
    db,
    wallet_address: str,
) -> dict[str, Any]:
    dna = calculate_wallet_dna(
        db,
        wallet_address,
    )

    return calculate_score_from_dna(
        wallet_address=wallet_address,
        dna=dna,
    ) 