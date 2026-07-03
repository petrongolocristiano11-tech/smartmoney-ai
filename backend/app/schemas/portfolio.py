from pydantic import BaseModel


class PortfolioPositionResponse(BaseModel):
    token_mint: str
    bought_amount: float
    sold_amount: float
    holding_amount: float
    buy_trades: int
    sell_trades: int
    total_sol_spent: float
    total_sol_received: float


class WalletPortfolioResponse(BaseModel):
    wallet: str
    tokens_count: int
    positions: list[PortfolioPositionResponse] 