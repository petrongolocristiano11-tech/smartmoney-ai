from backend.app.services.signals_engine import (
    SIGNAL_VERSION,
    get_token_signals,
)


def get_alerts(
    db,
    min_signal_score: float = 70,
):
    signal_payload = get_token_signals(
        db=db,
        min_buyers=2,
    )

    alerts = []

    for signal in signal_payload[
        "signals"
    ]:
        if signal["buyers"] < 2:
            continue

        if (
            signal["average_smart_score"]
            < 60
        ):
            continue

        if signal["average_roi"] <= 0:
            continue

        if (
            signal["evidence_score"]
            < 35
        ):
            continue

        if (
            signal["signal_score"]
            < min_signal_score
        ):
            continue

        if signal["confidence"] == "LOW":
            continue

        if (
            "HIGH_VOLUME_CONCENTRATION"
            in signal["risk_flags"]
            and signal["buyers"] < 3
        ):
            continue

        alert_type = (
            "STRONG_SMART_ACCUMULATION"
            if signal["confidence"]
            == "HIGH"
            else "SMART_ACCUMULATION"
        )

        alerts.append(
            {
                "version": (
                    SIGNAL_VERSION
                ),
                "type": alert_type,
                "token": (
                    signal[
                        "token_mint"
                    ]
                ),
                "signal_score": (
                    signal[
                        "signal_score"
                    ]
                ),
                "evidence_score": (
                    signal[
                        "evidence_score"
                    ]
                ),
                "confidence": (
                    signal[
                        "confidence"
                    ]
                ),
                "leader_wallet": (
                    signal[
                        "leader_wallet"
                    ]
                ),
                "buyers": (
                    signal["buyers"]
                ),
                "unique_buy_trades": (
                    signal[
                        "unique_buy_trades"
                    ]
                ),
                "average_smart_score": (
                    signal[
                        "average_smart_score"
                    ]
                ),
                "average_roi": (
                    signal[
                        "average_roi"
                    ]
                ),
                "average_prediction_score": (
                    signal[
                        "average_prediction_score"
                    ]
                ),
                "total_volume_sol": (
                    signal[
                        "total_volume_sol"
                    ]
                ),
                "smart_volume_share_percent": (
                    signal[
                        "smart_volume_share_percent"
                    ]
                ),
                "volume_concentration_percent": (
                    signal[
                        "volume_concentration_percent"
                    ]
                ),
                "latest_buy_at": (
                    signal[
                        "latest_buy_at"
                    ]
                ),
                "age_hours": (
                    signal[
                        "age_hours"
                    ]
                ),
                "risk_flags": (
                    signal[
                        "risk_flags"
                    ]
                ),
                "reasons": (
                    signal["reasons"]
                ),
            }
        )

    alerts.sort(
        key=lambda item: (
            item["signal_score"],
            item["evidence_score"],
            item["buyers"],
        ),
        reverse=True,
    )

    return {
        "version": SIGNAL_VERSION,
        "generated_at": (
            signal_payload[
                "generated_at"
            ]
        ),
        "count": len(alerts),
        "alerts": alerts,
    } 