from pydantic import BaseModel


class WalletPredictionResponse(BaseModel):
    wallet: str

    tokens_analyzed: int

    successful_tokens: int

    prediction_score: float 