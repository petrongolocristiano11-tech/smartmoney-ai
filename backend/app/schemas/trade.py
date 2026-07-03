from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TradeResponse(BaseModel):
    id: int
    signature: str
    wallet_address: str
    side: str
    source: str | None
    token_mint: str | None
    token_amount: float | None
    sol_amount: float | None
    fee: float | None
    success: bool
    block_time: datetime | None
    raw_json: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True) 