from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DiscoveredWalletResponse(BaseModel):
    id: int
    wallet_address: str
    discovered_from_token: str | None

    smart_score: float
    ranking_score: float
    roi_percent: float
    win_rate_percent: float
    profit_loss_sol: float
    reliable_positions: int

    last_swap_at: datetime | None
    swaps_24h: int
    swaps_7d: int
    buys_24h: int
    sells_24h: int
    buys_7d: int
    sells_7d: int
    volume_24h_sol: float
    volume_7d_sol: float
    active_days_7d: int
    average_swaps_per_active_day_7d: float
    average_minutes_between_swaps_7d: float | None
    activity_score: float
    activity_classification: str
    activity_eligible: bool
    activity_reasons: list[str]
    activity_calculated_at: datetime | None

    eligible: bool
    eligibility_reasons: list[str]
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DiscoveredWalletActivityRefreshResponse(BaseModel):
    status: str
    wallets_refreshed: int
    helius_requests: int
    message: str
