from pydantic import BaseModel, ConfigDict


class WalletCreate(BaseModel):
    address: str


class WalletResponse(BaseModel):
    id: int
    address: str
    smart_score: float
    win_rate: float
    roi: float
    total_profit: float
    active: bool

    model_config = ConfigDict(from_attributes=True) 