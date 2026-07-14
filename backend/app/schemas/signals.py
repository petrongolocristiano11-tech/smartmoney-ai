from pydantic import BaseModel


class SignalComponentsResponse(
    BaseModel
):
    wallet_quality: float
    prediction_quality: float
    conviction_quality: float
    roi_quality: float
    buyer_consensus: float
    recency: float
    volume_diversity: float
    volume_strength: float


class TokenSignal(BaseModel):
    version: str
    token_mint: str

    buyers: int
    unique_buy_trades: int

    leader_wallet: str | None
    leader_smart_score: float

    average_smart_score: float
    average_roi: float
    average_prediction_score: float
    average_conviction_score: float

    signal_score: float
    raw_signal_score: float
    evidence_score: float
    confidence: str

    total_volume_sol: float
    smart_volume_share_percent: float
    volume_concentration_percent: float

    latest_buy_at: str
    age_hours: float

    risk_penalty: float
    risk_flags: list[str]
    reasons: list[str]

    components: SignalComponentsResponse


class TokenSignalsResponse(BaseModel):
    version: str
    generated_at: str
    lookback_hours: int
    count: int
    signals: list[TokenSignal] 