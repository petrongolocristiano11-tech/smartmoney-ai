from datetime import (
    datetime,
    timedelta,
    timezone,
)
from types import SimpleNamespace

from backend.app.services.signals_engine import (
    SIGNAL_VERSION,
    build_token_signal,
    calculate_consensus_score,
    calculate_recency_score,
    calculate_volume_diversity_score,
)


NOW = datetime(
    2026,
    7,
    14,
    12,
    0,
    tzinfo=timezone.utc,
)


def make_profile(
    wallet: str,
    smart_score: float = 80,
    roi: float = 50,
    prediction_score: float = 75,
    conviction_score: float = 70,
    risk: str = "LOW",
):
    return SimpleNamespace(
        wallet_address=wallet,
        smart_score=smart_score,
        roi=roi,
        prediction_score=(
            prediction_score
        ),
        conviction_score=(
            conviction_score
        ),
        risk=risk,
    )


def make_trade(
    wallet: str,
    volume: float,
    age_hours: float = 1,
):
    return SimpleNamespace(
        wallet_address=wallet,
        token_mint="TOKEN",
        sol_amount=volume,
        side="BUY",
        success=True,
        block_time=(
            NOW
            - timedelta(
                hours=age_hours
            )
        ),
        created_at=None,
    )


def build_strong_signal():
    profiles = {
        "wallet-1": make_profile(
            "wallet-1",
            smart_score=82,
            roi=55,
            prediction_score=78,
        ),
        "wallet-2": make_profile(
            "wallet-2",
            smart_score=79,
            roi=45,
            prediction_score=74,
        ),
        "wallet-3": make_profile(
            "wallet-3",
            smart_score=77,
            roi=40,
            prediction_score=72,
        ),
    }

    trades = [
        make_trade(
            "wallet-1",
            2.0,
            age_hours=1,
        ),
        make_trade(
            "wallet-1",
            0.5,
            age_hours=2,
        ),
        make_trade(
            "wallet-2",
            2.0,
            age_hours=2,
        ),
        make_trade(
            "wallet-2",
            0.5,
            age_hours=3,
        ),
        make_trade(
            "wallet-3",
            2.0,
            age_hours=1,
        ),
    ]

    return build_token_signal(
        token_mint="TOKEN",
        trades=trades,
        profiles=profiles,
        min_buyers=2,
        now=NOW,
    )


def test_consensus_increases_with_buyers():
    assert (
        calculate_consensus_score(4)
        > calculate_consensus_score(2)
    )


def test_recent_activity_scores_higher():
    assert (
        calculate_recency_score(1)
        > calculate_recency_score(300)
    )


def test_diversification_penalizes_concentration():
    diversified = (
        calculate_volume_diversity_score(
            0.35
        )
    )

    concentrated = (
        calculate_volume_diversity_score(
            0.90
        )
    )

    assert diversified > concentrated


def test_signal_requires_minimum_buyers():
    profiles = {
        "wallet-1": make_profile(
            "wallet-1"
        ),
    }

    result = build_token_signal(
        token_mint="TOKEN",
        trades=[
            make_trade(
                "wallet-1",
                2,
            ),
        ],
        profiles=profiles,
        min_buyers=2,
        now=NOW,
    )

    assert result is None


def test_strong_signal_has_good_evidence():
    result = build_strong_signal()

    assert result is not None
    assert (
        result["version"]
        == SIGNAL_VERSION
    )
    assert result["buyers"] == 3
    assert result["signal_score"] > 70
    assert result["evidence_score"] > 60
    assert result["confidence"] in {
        "MEDIUM",
        "HIGH",
    }
    assert (
        "HIGH_VOLUME_CONCENTRATION"
        not in result["risk_flags"]
    )


def test_concentrated_volume_is_flagged():
    profiles = {
        "wallet-1": make_profile(
            "wallet-1"
        ),
        "wallet-2": make_profile(
            "wallet-2"
        ),
    }

    result = build_token_signal(
        token_mint="TOKEN",
        trades=[
            make_trade(
                "wallet-1",
                9,
            ),
            make_trade(
                "wallet-2",
                1,
            ),
        ],
        profiles=profiles,
        min_buyers=2,
        now=NOW,
    )

    assert result is not None

    assert (
        "HIGH_VOLUME_CONCENTRATION"
        in result["risk_flags"]
    )


def test_negative_roi_reduces_signal():
    positive = build_strong_signal()

    negative_profiles = {
        "wallet-1": make_profile(
            "wallet-1",
            roi=-50,
        ),
        "wallet-2": make_profile(
            "wallet-2",
            roi=-50,
        ),
        "wallet-3": make_profile(
            "wallet-3",
            roi=-50,
        ),
    }

    trades = [
        make_trade(
            "wallet-1",
            2,
        ),
        make_trade(
            "wallet-2",
            2,
        ),
        make_trade(
            "wallet-3",
            2,
        ),
    ]

    negative = build_token_signal(
        token_mint="TOKEN",
        trades=trades,
        profiles=negative_profiles,
        min_buyers=2,
        now=NOW,
    )

    assert positive is not None
    assert negative is not None

    assert (
        negative["signal_score"]
        < positive["signal_score"]
    )

    assert (
        "NEGATIVE_AVERAGE_ROI"
        in negative["risk_flags"]
    )


def test_stale_activity_is_penalized():
    profiles = {
        "wallet-1": make_profile(
            "wallet-1"
        ),
        "wallet-2": make_profile(
            "wallet-2"
        ),
        "wallet-3": make_profile(
            "wallet-3"
        ),
    }

    recent = build_token_signal(
        token_mint="TOKEN",
        trades=[
            make_trade(
                "wallet-1",
                2,
                1,
            ),
            make_trade(
                "wallet-2",
                2,
                1,
            ),
            make_trade(
                "wallet-3",
                2,
                1,
            ),
        ],
        profiles=profiles,
        min_buyers=2,
        now=NOW,
    )

    stale = build_token_signal(
        token_mint="TOKEN",
        trades=[
            make_trade(
                "wallet-1",
                2,
                500,
            ),
            make_trade(
                "wallet-2",
                2,
                500,
            ),
            make_trade(
                "wallet-3",
                2,
                500,
            ),
        ],
        profiles=profiles,
        min_buyers=2,
        now=NOW,
    )

    assert recent is not None
    assert stale is not None

    assert (
        stale["signal_score"]
        < recent["signal_score"]
    )

    assert (
        "STALE_ACTIVITY"
        in stale["risk_flags"]
    ) 