from pydantic import BaseModel


class CopyTradingSimulationResponse(BaseModel):
    wallet: str
    starting_capital: float
    final_capital: float
    profit: float
    roi: float
    positions: int
    wins: int
    losses: int
    risk: str 