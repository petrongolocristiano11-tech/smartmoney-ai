from pydantic import BaseModel

from backend.app.schemas.analytics import WalletAnalyticsResponse


class SmartScoreComponentsResponse(BaseModel):
    roi_score: float
    win_rate_score: float
    profit_score: float
    activity_score: float


class SmartScoreWeightsResponse(BaseModel):
    roi: float
    win_rate: float
    profit: float
    activity: float


class SmartScoreResponse(BaseModel):
    wallet: str
    smart_score: float
    components: SmartScoreComponentsResponse
    weights: SmartScoreWeightsResponse
    analytics: WalletAnalyticsResponse 