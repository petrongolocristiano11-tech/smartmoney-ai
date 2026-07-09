from pydantic import BaseModel


class WalletConvictionResponse(BaseModel):
    wallet: str

    tokens_analyzed: int

    average_position_size: float

    average_buys_per_token: float

    average_sells_per_token: float

    average_sol_per_token: float

    accumulation_score: float

    conviction_score: float 