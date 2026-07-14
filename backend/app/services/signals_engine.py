from collections import defaultdict
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from math import exp, log1p, tanh
from typing import Any

from sqlalchemy.orm import Session

from backend.app.models.trade import Trade
from backend.app.models.wallet_profile import (
    WalletProfile,
)


SIGNAL_VERSION = "2.0"

DEFAULT_LOOKBACK_HOURS = 30 * 24
SMART_WALLET_THRESHOLD = 60.0


SIGNAL_WEIGHTS = {
    "wallet_quality": 0.28,
    "prediction_quality": 0.15,
    "conviction_quality": 0.10,
    "roi_quality": 0.10,
    "buyer_consensus": 0.15,
    "recency": 0.10,
    "volume_diversity": 0.07,
    "volume_strength": 0.05,
}


def _read_value(
    source: Any,
    key: str,
    default: Any = None,
) -> Any:
    if isinstance(source, dict):
        return source.get(key, default)

    return getattr(source, key, default)


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
    minimum: float = 0.0,
    maximum: float = 100.0,
) -> float:
    return max(
        minimum,
        min(_as_float(value), maximum),
    )


def _to_utc(
    value: datetime | None,
) -> datetime | None:
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(timezone.utc)


def _trade_timestamp(
    trade: Any,
) -> datetime | None:
    return _to_utc(
        _read_value(trade, "block_time")
        or _read_value(trade, "created_at")
    )


def normalize_roi_score(
    roi_percent: float,
) -> float:
    return clamp(
        50
        + 50
        * tanh(
            _as_float(roi_percent)
            / 75
        )
    )


def calculate_consensus_score(
    buyers: int,
) -> float:
    normalized_buyers = max(
        int(buyers),
        0,
    )

    return clamp(
        (
            1
            - exp(
                -normalized_buyers / 3
            )
        )
        * 100
    )


def calculate_recency_score(
    age_hours: float,
) -> float:
    normalized_age = max(
        _as_float(age_hours),
        0,
    )

    return clamp(
        100
        * exp(
            -normalized_age / 168
        )
    )


def calculate_volume_score(
    volume_sol: float,
) -> float:
    normalized_volume = max(
        _as_float(volume_sol),
        0,
    )

    if normalized_volume <= 0:
        return 0.0

    return clamp(
        log1p(normalized_volume)
        / log1p(10)
        * 100
    )


def calculate_volume_diversity_score(
    concentration: float,
) -> float:
    normalized_concentration = max(
        0.0,
        min(
            _as_float(concentration),
            1.0,
        ),
    )

    return clamp(
        (
            1
            - normalized_concentration
        )
        * 150
    )


def calculate_signal_evidence(
    buyer_consensus: float,
    trade_sample_score: float,
    volume_diversity: float,
    smart_volume_share: float,
) -> float:
    return clamp(
        buyer_consensus * 0.45
        + trade_sample_score * 0.20
        + volume_diversity * 0.25
        + smart_volume_share * 0.10
    )


def get_signal_confidence(
    signal_score: float,
    evidence_score: float,
    buyers: int,
    average_roi: float,
) -> str:
    if (
        signal_score >= 75
        and evidence_score >= 65
        and buyers >= 3
        and average_roi > 0
    ):
        return "HIGH"

    if (
        signal_score >= 60
        and evidence_score >= 35
        and buyers >= 2
    ):
        return "MEDIUM"

    return "LOW"


def build_token_signal(
    token_mint: str,
    trades: list[Any],
    profiles: dict[str, Any],
    min_buyers: int = 1,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    current_time = _to_utc(now)

    if current_time is None:
        current_time = datetime.now(
            timezone.utc
        )

    all_volume_sol = 0.0

    smart_wallets: dict[
        str,
        dict[str, Any],
    ] = {}

    for trade in trades:
        if (
            _read_value(
                trade,
                "success",
                True,
            )
            is False
        ):
            continue

        wallet_address = str(
            _read_value(
                trade,
                "wallet_address",
                "",
            )
            or ""
        ).strip()

        if not wallet_address:
            continue

        sol_amount = max(
            _as_float(
                _read_value(
                    trade,
                    "sol_amount",
                    0,
                )
            ),
            0,
        )

        all_volume_sol += sol_amount

        profile = profiles.get(
            wallet_address
        )

        if profile is None:
            continue

        smart_score = _as_float(
            _read_value(
                profile,
                "smart_score",
                0,
            )
        )

        if (
            smart_score
            < SMART_WALLET_THRESHOLD
        ):
            continue

        timestamp = _trade_timestamp(
            trade
        )

        wallet_data = smart_wallets.setdefault(
            wallet_address,
            {
                "profile": profile,
                "volume_sol": 0.0,
                "buy_trades": 0,
                "latest_buy_at": None,
            },
        )

        wallet_data["volume_sol"] += (
            sol_amount
        )

        wallet_data["buy_trades"] += 1

        previous_timestamp = wallet_data[
            "latest_buy_at"
        ]

        if (
            timestamp is not None
            and (
                previous_timestamp is None
                or timestamp
                > previous_timestamp
            )
        ):
            wallet_data[
                "latest_buy_at"
            ] = timestamp

    buyers = len(smart_wallets)

    if buyers < min_buyers:
        return None

    wallet_rows = list(
        smart_wallets.items()
    )

    smart_volume_sol = sum(
        row["volume_sol"]
        for _, row in wallet_rows
    )

    unique_buy_trades = sum(
        row["buy_trades"]
        for _, row in wallet_rows
    )

    average_smart_score = sum(
        _as_float(
            _read_value(
                row["profile"],
                "smart_score",
                0,
            )
        )
        for _, row in wallet_rows
    ) / buyers

    average_roi = sum(
        _as_float(
            _read_value(
                row["profile"],
                "roi",
                0,
            )
        )
        for _, row in wallet_rows
    ) / buyers

    average_prediction_score = sum(
        _as_float(
            _read_value(
                row["profile"],
                "prediction_score",
                0,
            )
        )
        for _, row in wallet_rows
    ) / buyers

    average_conviction_score = sum(
        _as_float(
            _read_value(
                row["profile"],
                "conviction_score",
                0,
            )
        )
        for _, row in wallet_rows
    ) / buyers

    leader_wallet, leader_data = max(
        wallet_rows,
        key=lambda item: _as_float(
            _read_value(
                item[1]["profile"],
                "smart_score",
                0,
            )
        ),
    )

    leader_score = _as_float(
        _read_value(
            leader_data["profile"],
            "smart_score",
            0,
        )
    )

    timestamps = [
        row["latest_buy_at"]
        for _, row in wallet_rows
        if row["latest_buy_at"]
        is not None
    ]

    latest_buy_at = (
        max(timestamps)
        if timestamps
        else current_time
    )

    age_hours = max(
        (
            current_time
            - latest_buy_at
        ).total_seconds()
        / 3600,
        0,
    )

    if smart_volume_sol > 0:
        largest_wallet_volume = max(
            row["volume_sol"]
            for _, row in wallet_rows
        )

        volume_concentration = (
            largest_wallet_volume
            / smart_volume_sol
        )
    else:
        volume_concentration = (
            1 / buyers
        )

    smart_volume_share = (
        smart_volume_sol
        / all_volume_sol
        * 100
        if all_volume_sol > 0
        else 0
    )

    buyer_consensus_score = (
        calculate_consensus_score(
            buyers
        )
    )

    recency_score = (
        calculate_recency_score(
            age_hours
        )
    )

    volume_diversity_score = (
        calculate_volume_diversity_score(
            volume_concentration
        )
    )

    volume_strength_score = (
        calculate_volume_score(
            smart_volume_sol
        )
    )

    roi_quality_score = (
        normalize_roi_score(
            average_roi
        )
    )

    trade_sample_score = clamp(
        unique_buy_trades
        / 8
        * 100
    )

    evidence_score = (
        calculate_signal_evidence(
            buyer_consensus=(
                buyer_consensus_score
            ),
            trade_sample_score=(
                trade_sample_score
            ),
            volume_diversity=(
                volume_diversity_score
            ),
            smart_volume_share=(
                smart_volume_share
            ),
        )
    )

    components = {
        "wallet_quality": clamp(
            average_smart_score
        ),
        "prediction_quality": clamp(
            average_prediction_score
        ),
        "conviction_quality": clamp(
            average_conviction_score
        ),
        "roi_quality": roi_quality_score,
        "buyer_consensus": (
            buyer_consensus_score
        ),
        "recency": recency_score,
        "volume_diversity": (
            volume_diversity_score
        ),
        "volume_strength": (
            volume_strength_score
        ),
    }

    raw_signal_score = sum(
        components[key]
        * SIGNAL_WEIGHTS[key]
        for key in SIGNAL_WEIGHTS
    )

    risk_flags: list[str] = []
    risk_penalty = 0.0

    risk_penalties = {
        "LOW": 0.0,
        "MEDIUM": 4.0,
        "HIGH": 12.0,
    }

    wallet_risk_penalty = sum(
        risk_penalties.get(
            str(
                _read_value(
                    row["profile"],
                    "risk",
                    "MEDIUM",
                )
            ).upper(),
            6.0,
        )
        for _, row in wallet_rows
    ) / buyers

    risk_penalty += (
        wallet_risk_penalty
    )

    high_risk_wallets = sum(
        1
        for _, row in wallet_rows
        if str(
            _read_value(
                row["profile"],
                "risk",
                "MEDIUM",
            )
        ).upper()
        == "HIGH"
    )

    if high_risk_wallets > 0:
        risk_flags.append(
            "HIGH_RISK_WALLETS"
        )

    if volume_concentration >= 0.70:
        risk_flags.append(
            "HIGH_VOLUME_CONCENTRATION"
        )

        risk_penalty += 8

    if average_roi < 0:
        risk_flags.append(
            "NEGATIVE_AVERAGE_ROI"
        )

        risk_penalty += 5

    if recency_score < 35:
        risk_flags.append(
            "STALE_ACTIVITY"
        )

        risk_penalty += 5

    if smart_volume_share < 50:
        risk_flags.append(
            "LOW_SMART_VOLUME_SHARE"
        )

        risk_penalty += 4

    if evidence_score < 35:
        risk_flags.append(
            "LOW_EVIDENCE"
        )

        risk_penalty += 5

    confidence_factor = (
        0.55
        + 0.45
        * evidence_score
        / 100
    )

    confidence_adjusted_score = (
        50
        + (
            raw_signal_score
            - 50
        )
        * confidence_factor
    )

    signal_score = clamp(
        confidence_adjusted_score
        - risk_penalty
    )

    confidence = get_signal_confidence(
        signal_score=signal_score,
        evidence_score=evidence_score,
        buyers=buyers,
        average_roi=average_roi,
    )

    reasons: list[str] = []

    if buyers >= 3:
        reasons.append(
            f"Consenso di {buyers} smart wallet"
        )

    if average_smart_score >= 70:
        reasons.append(
            "Qualità media dei wallet elevata"
        )

    if average_prediction_score >= 65:
        reasons.append(
            "Prediction score medio positivo"
        )

    if recency_score >= 70:
        reasons.append(
            "Attività di acquisto recente"
        )

    if (
        volume_diversity_score >= 65
        and buyers >= 2
    ):
        reasons.append(
            "Volume distribuito tra più wallet"
        )

    if smart_volume_share >= 70:
        reasons.append(
            "Gran parte del volume proviene "
            "da smart wallet"
        )

    if not reasons:
        reasons.append(
            "Segnale con evidenza ancora limitata"
        )

    return {
        "version": SIGNAL_VERSION,
        "token_mint": token_mint,
        "buyers": buyers,
        "unique_buy_trades": (
            unique_buy_trades
        ),
        "leader_wallet": leader_wallet,
        "leader_smart_score": round(
            leader_score,
            2,
        ),
        "average_smart_score": round(
            average_smart_score,
            2,
        ),
        "average_roi": round(
            average_roi,
            2,
        ),
        "average_prediction_score": round(
            average_prediction_score,
            2,
        ),
        "average_conviction_score": round(
            average_conviction_score,
            2,
        ),
        "signal_score": round(
            signal_score,
            2,
        ),
        "raw_signal_score": round(
            raw_signal_score,
            2,
        ),
        "evidence_score": round(
            evidence_score,
            2,
        ),
        "confidence": confidence,
        "total_volume_sol": round(
            smart_volume_sol,
            6,
        ),
        "smart_volume_share_percent": round(
            smart_volume_share,
            2,
        ),
        "volume_concentration_percent": round(
            volume_concentration * 100,
            2,
        ),
        "latest_buy_at": (
            latest_buy_at.isoformat()
        ),
        "age_hours": round(
            age_hours,
            2,
        ),
        "risk_penalty": round(
            risk_penalty,
            2,
        ),
        "risk_flags": risk_flags,
        "reasons": reasons,
        "components": {
            key: round(value, 2)
            for key, value
            in components.items()
        },
    }


def get_token_signals(
    db: Session,
    min_buyers: int = 1,
    lookback_hours: int = (
        DEFAULT_LOOKBACK_HOURS
    ),
):
    current_time = datetime.now(
        timezone.utc
    )

    normalized_lookback = max(
        int(lookback_hours),
        1,
    )

    cutoff = current_time - timedelta(
        hours=normalized_lookback
    )

    buys = (
        db.query(Trade)
        .filter(
            Trade.side == "BUY"
        )
        .filter(
            Trade.token_mint.isnot(None)
        )
        .all()
    )

    profiles = {
        profile.wallet_address: profile
        for profile in (
            db.query(WalletProfile).all()
        )
    }

    grouped: dict[
        str,
        list[Trade],
    ] = defaultdict(list)

    for trade in buys:
        timestamp = _trade_timestamp(
            trade
        )

        if (
            timestamp is None
            or timestamp < cutoff
        ):
            continue

        if trade.token_mint:
            grouped[
                trade.token_mint
            ].append(trade)

    signals = []

    for token_mint, token_trades in (
        grouped.items()
    ):
        signal = build_token_signal(
            token_mint=token_mint,
            trades=token_trades,
            profiles=profiles,
            min_buyers=min_buyers,
            now=current_time,
        )

        if signal is not None:
            signals.append(signal)

    signals.sort(
        key=lambda item: (
            item["signal_score"],
            item["evidence_score"],
            item["buyers"],
            item["latest_buy_at"],
        ),
        reverse=True,
    )

    return {
        "version": SIGNAL_VERSION,
        "generated_at": (
            current_time.isoformat()
        ),
        "lookback_hours": (
            normalized_lookback
        ),
        "count": len(signals),
        "signals": signals,
    } 