from pydantic import BaseModel


class WalletAnalyticsResponse(BaseModel):
    wallet: str
    tokens_analyzed: int
    reliable_positions: int
    total_sol_spent: float
    total_sol_received: float
    total_profit_loss_sol: float
    total_roi_percent: float
    win_rate_percent: float
    winning_positions: int
    losing_positions: int 