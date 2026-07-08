from pydantic import BaseModel

from backend.app.schemas.analytics import WalletAnalyticsResponse


class SmartScoreComponentsResponse(BaseModel):
    roi_score: float
    win_rate_score: float
    profit_score: float
    activity_score: float
    avg_trade_size_score: float
    profit_per_token_score: float
    early_buyer_score: float
    buy_sell_balance_score: float
    risk_score: float


class SmartScoreWeightsResponse(BaseModel):
    roi: float
    win_rate: float
    profit: float
    activity: float
    avg_trade_size: float
    profit_per_token: float
    early_buyer: float
    buy_sell_balance: float
    risk: float


class EarlyBuyerResponse(BaseModel):
    wallet: str
    tokens_analyzed: int
    early_entries: int
    early_rank_threshold: int
    early_buyer_score: float
    average_entry_rank: float
    best_entry_rank: int
    worst_entry_rank: int


class SmartScoreResponse(BaseModel):
    wallet: str
    smart_score: float
    version: str
    components: SmartScoreComponentsResponse
    weights: SmartScoreWeightsResponse
    analytics: WalletAnalyticsResponse
    early_buyer: EarlyBuyerResponse 