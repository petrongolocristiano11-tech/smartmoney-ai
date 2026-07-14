from typing import Any

from pydantic import BaseModel


class SmartScoreComponentsResponse(
    BaseModel
):
    performance_score: float
    timing_score: float
    leadership_score: float
    conviction_score: float
    holding_score: float
    prediction_score: float
    risk_score: float
    consistency_score: float
    data_quality_score: float


class SmartScoreWeightsResponse(
    BaseModel
):
    performance: float
    timing: float
    leadership: float
    conviction: float
    holding: float
    prediction: float
    risk: float
    consistency: float
    data_quality: float


class SmartScorePenaltyResponse(
    BaseModel
):
    code: str
    points: float


class SmartScoreResponse(BaseModel):
    wallet: str
    smart_score: float
    raw_score: float
    confidence: float
    evidence_level: str
    penalty_points: float
    penalties: list[
        SmartScorePenaltyResponse
    ]
    reasons: list[str]
    version: str
    components: (
        SmartScoreComponentsResponse
    )
    weights: SmartScoreWeightsResponse
    dna: dict[str, Any] 