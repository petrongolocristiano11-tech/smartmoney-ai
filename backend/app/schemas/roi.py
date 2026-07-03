from pydantic import BaseModel


class RoiPositionResponse(BaseModel):
    token_mint: str
    bought_amount: float
    sold_amount: float
    holding_amount: float
    buy_trades: int
    sell_trades: int
    total_sol_spent: float
    total_sol_received: float
    profit_loss_sol: float
    roi_percent: float
    roi_reliable: bool
    min_sol_required: float


class WalletRoiResponse(BaseModel):
    wallet: str
    tokens: int
    positions: list[RoiPositionResponse] 