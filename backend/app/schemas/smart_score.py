from typing import Any

from pydantic import BaseModel


class SmartScoreComponentsResponse(BaseModel):
    performance_score: float
    timing_score: float
    leadership_score: float
    conviction_score: float
    holding_score: float
    prediction_score: float
    risk_score: float


class SmartScoreWeightsResponse(BaseModel):
    performance: float
    timing: float
    leadership: float
    conviction: float
    holding: float
    prediction: float
    risk: float


class SmartScoreResponse(BaseModel):
    wallet: str
    smart_score: float
    version: str
    components: SmartScoreComponentsResponse
    weights: SmartScoreWeightsResponse
    dna: dict[str, Any] 