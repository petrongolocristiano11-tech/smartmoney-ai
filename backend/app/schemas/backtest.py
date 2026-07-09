from pydantic import BaseModel


class WalletBacktestResponse(BaseModel):
    wallet: str

    positions: int
    wins: int
    losses: int

    win_rate: float
    roi: float

    profit_loss_sol: float
    average_profit_per_position: float

    risk: str 