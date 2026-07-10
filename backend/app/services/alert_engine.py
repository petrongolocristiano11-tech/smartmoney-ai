from backend.app.services.signals_engine import get_token_signals


def get_alerts(
    db,
    min_signal_score: float = 70,
):
    signals = get_token_signals(db)["signals"]

    alerts = []

    for signal in signals:

        # Deve esserci almeno più di un wallet smart
        if signal["buyers"] < 2:
            continue

        # Wallet mediamente intelligenti
        if signal["average_smart_score"] < 60:
            continue

        # ROI medio positivo
        if signal["average_roi"] <= 0:
            continue

        # Signal Score sufficiente
        if signal["signal_score"] < min_signal_score:
            continue

        alerts.append(
            {
                "type": "SMART_ACCUMULATION",
                "token": signal["token_mint"],
                "signal_score": signal["signal_score"],
                "confidence": signal["confidence"],
                "leader_wallet": signal["leader_wallet"],
                "buyers": signal["buyers"],
                "average_smart_score": signal["average_smart_score"],
                "average_roi": signal["average_roi"],
                "total_volume_sol": signal["total_volume_sol"],
            }
        )

    alerts.sort(
        key=lambda item: item["signal_score"],
        reverse=True,
    )

    return {
        "count": len(alerts),
        "alerts": alerts,
    } 