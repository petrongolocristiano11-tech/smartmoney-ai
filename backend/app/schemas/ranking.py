from pydantic import BaseModel


class RankingWalletResponse(BaseModel):
    wallet: str
    smart_score: float
    roi_percent: float
    win_rate_percent: float
    profit_loss_sol: float
    reliable_positions: int


class WalletRankingResponse(BaseModel):
    wallets_found: int
    ranking: list[RankingWalletResponse] 