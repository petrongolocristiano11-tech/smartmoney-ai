from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DiscoveredWalletResponse(BaseModel):
    id: int
    wallet_address: str
    discovered_from_token: str | None
    smart_score: float
    roi_percent: float
    win_rate_percent: float
    profit_loss_sol: float
    reliable_positions: int
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True) 