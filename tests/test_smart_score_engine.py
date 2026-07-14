from copy import deepcopy

from backend.app.services.smart_score_engine import (
    SMART_SCORE_VERSION,
    calculate_data_quality_score,
    calculate_score_from_dna,
    clamp,
    normalize_symmetric,
    ratio_to_score,
    smoothed_success_rate,
)


def build_strong_dna():
    return {
        "analytics": {
            "winning_positions": 9,
            "losing_positions": 3,
            "reliable_positions": 12,
            "total_trades": 50,
            "unique_tokens": 10,
            "total_roi_percent": 120,
            "profit_per_token": 0.5,
            "total_profit_loss_sol": 4,
            "buy_trades": 25,
            "sell_trades": 25,
            "buy_sell_ratio": 1,
            "risk_level": "LOW",
        },
        "early_buyer": {
            "early_buyer_score": 80,
        },
        "influence": {
            "influence_score": 75,
        },
        "conviction": {
            "conviction_score": 70,
        },
        "holding": {
            "holding_score": 90,
        },
        "prediction": {
            "prediction_score": 75,
        },
    }


def test_clamp_middle_value():
    assert clamp(50) == 50


def test_clamp_minimum():
    assert clamp(-10) == 0


def test_clamp_maximum():
    assert clamp(150) == 100


def test_symmetric_normalization():
    assert normalize_symmetric(
        0,
        100,
    ) == 50

    assert normalize_symmetric(
        100,
        100,
    ) > 50

    assert normalize_symmetric(
        -100,
        100,
    ) < 50


def test_ratio_to_score_is_capped():
    assert ratio_to_score(5, 10) == 50
    assert ratio_to_score(20, 10) == 100


def test_smoothed_rate_reduces_small_sample():
    one_out_of_one = (
        smoothed_success_rate(
            successes=1,
            total=1,
        )
    )

    ten_out_of_ten = (
        smoothed_success_rate(
            successes=10,
            total=10,
        )
    )

    assert one_out_of_one < 70
    assert ten_out_of_ten > one_out_of_one


def test_strong_wallet_has_high_evidence():
    dna = build_strong_dna()

    result = calculate_score_from_dna(
        wallet_address="strong-wallet",
        dna=dna,
    )

    assert (
        result["version"]
        == SMART_SCORE_VERSION
    )

    assert result["evidence_level"] == "HIGH"
    assert result["confidence"] == 100
    assert result["smart_score"] > 70
    assert result["penalty_points"] == 0


def test_sparse_wallet_is_penalized():
    strong_dna = build_strong_dna()
    sparse_dna = deepcopy(strong_dna)

    sparse_dna["analytics"].update(
        {
            "winning_positions": 1,
            "losing_positions": 0,
            "reliable_positions": 0,
            "total_trades": 1,
            "unique_tokens": 1,
            "buy_trades": 1,
            "sell_trades": 0,
            "buy_sell_ratio": 1,
            "risk_level": "MEDIUM",
        }
    )

    strong_result = (
        calculate_score_from_dna(
            wallet_address="strong-wallet",
            dna=strong_dna,
        )
    )

    sparse_result = (
        calculate_score_from_dna(
            wallet_address="sparse-wallet",
            dna=sparse_dna,
        )
    )

    assert sparse_result[
        "evidence_level"
    ] == "LOW"

    assert (
        sparse_result["confidence"]
        < strong_result["confidence"]
    )

    assert (
        sparse_result["smart_score"]
        < strong_result["smart_score"]
    )

    assert (
        sparse_result["penalty_points"]
        > 0
    )


def test_negative_wallet_scores_low():
    dna = build_strong_dna()

    dna["analytics"].update(
        {
            "winning_positions": 1,
            "losing_positions": 9,
            "reliable_positions": 10,
            "total_trades": 40,
            "unique_tokens": 8,
            "total_roi_percent": -80,
            "profit_per_token": -0.2,
            "total_profit_loss_sol": -2,
            "buy_trades": 20,
            "sell_trades": 20,
            "buy_sell_ratio": 1,
            "risk_level": "HIGH",
        }
    )

    dna["early_buyer"][
        "early_buyer_score"
    ] = 20

    dna["influence"][
        "influence_score"
    ] = 20

    dna["conviction"][
        "conviction_score"
    ] = 30

    dna["holding"][
        "holding_score"
    ] = 40

    dna["prediction"][
        "prediction_score"
    ] = 10

    result = calculate_score_from_dna(
        wallet_address="negative-wallet",
        dna=dna,
    )

    assert result["smart_score"] < 40
    assert result["penalty_points"] > 0


def test_data_quality_requires_depth():
    low_quality = {
        "total_trades": 1,
        "unique_tokens": 1,
        "reliable_positions": 0,
        "winning_positions": 1,
        "losing_positions": 0,
    }

    high_quality = {
        "total_trades": 50,
        "unique_tokens": 10,
        "reliable_positions": 12,
        "winning_positions": 9,
        "losing_positions": 3,
    }

    assert (
        calculate_data_quality_score(
            low_quality
        )
        < calculate_data_quality_score(
            high_quality
        )
    ) 