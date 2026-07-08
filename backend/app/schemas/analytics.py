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

    total_trades: int
    buy_trades: int
    sell_trades: int
    unique_tokens: int
    total_sol_volume: float
    average_trade_size_sol: float
    buy_sell_ratio: float
    profit_per_token: float
    risk_level: str 