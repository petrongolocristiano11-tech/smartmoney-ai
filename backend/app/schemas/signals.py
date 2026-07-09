from pydantic import BaseModel


class TokenSignal(BaseModel):
    token_mint: str
    buyers: int

    leader_wallet: str | None

    average_smart_score: float
    average_roi: float

    signal_score: float
    confidence: str

    total_volume_sol: float


class TokenSignalsResponse(BaseModel):
    signals: list[TokenSignal] 