from pydantic import BaseModel


class RankedWalletResponse(BaseModel):
    wallet: str
    smart_score: float
    version: str
    classification: str
    traits: list[str]
    roi_percent: float
    win_rate_percent: float
    profit_loss_sol: float


class WalletRankingResponse(BaseModel):
    count: int
    ranking: list[RankedWalletResponse] 