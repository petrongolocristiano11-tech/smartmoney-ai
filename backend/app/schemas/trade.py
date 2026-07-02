from datetime import datetime

from pydantic import BaseModel


class TradeBase(BaseModel):
    wallet_id: int
    token_id: int
    amount: float
    price: float


class TradeCreate(TradeBase):
    pass


class TradeResponse(TradeBase):
    id: int
    created_at: datetime

    model_config = {
        "from_attributes": True
    } 