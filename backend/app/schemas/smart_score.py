from pydantic import BaseModel

from backend.app.schemas.analytics import WalletAnalyticsResponse


class SmartScoreComponentsResponse(BaseModel):
    roi_score: float
    win_rate_score: float
    profit_score: float
    activity_score: float
    avg_trade_size_score: float
    profit_per_token_score: float
    risk_score: float


class SmartScoreWeightsResponse(BaseModel):
    roi: float
    win_rate: float
    profit: float
    activity: float
    avg_trade_size: float
    profit_per_token: float
    risk: float


class SmartScoreResponse(BaseModel):
    wallet: str
    smart_score: float
    version: str
    components: SmartScoreComponentsResponse
    weights: SmartScoreWeightsResponse
    analytics: WalletAnalyticsResponse 