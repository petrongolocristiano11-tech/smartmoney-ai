from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CandidateBacktestRequest(BaseModel):
    wallet_address: str = Field(min_length=32, max_length=64)
    lookback_days: int = Field(default=7, ge=1, le=30)
    starting_capital_sol: float = Field(default=1.0, gt=0, le=1000)
    fixed_buy_size_sol: float = Field(default=0.05, gt=0, le=100)
    slippage_bps: int = Field(default=100, ge=0, le=1000)
    fee_bps: int = Field(default=10, ge=0, le=500)
    copy_delay_seconds: int = Field(default=8, ge=0, le=3600)
    delay_penalty_bps_per_minute: float = Field(default=25.0, ge=0, le=500)
    max_open_positions: int = Field(default=5, ge=1, le=50)
    check_jupiter: bool = True
    jupiter_token_limit: int = Field(default=10, ge=1, le=20)

    @field_validator("wallet_address")
    @classmethod
    def normalize_wallet(cls, value: str) -> str:
        wallet = str(value or "").strip()
        if not 32 <= len(wallet) <= 64:
            raise ValueError("Wallet address non valido")
        return wallet


class CandidateBacktestResponse(BaseModel):
    id: int
    run_id: str
    wallet_address: str
    status: str
    decision: str
    score: float
    reasons: list[str]
    parameters: dict
    safety: dict

    source_trades: int
    valid_priced_trades: int
    buy_signals: int
    sell_signals: int
    executed_buys: int
    completed_positions: int
    winning_positions: int
    losing_positions: int
    breakeven_positions: int
    open_positions: int
    skipped_invalid: int
    skipped_existing_position: int
    skipped_max_positions: int
    skipped_insufficient_capital: int
    unmatched_sells: int
    unique_tokens: int

    starting_capital_sol: float
    ending_equity_sol: float
    realized_pnl_sol: float
    unrealized_pnl_sol: float
    net_pnl_sol: float
    total_return_percent: float
    win_rate_percent: float
    profit_factor: float | None
    max_drawdown_percent: float
    execution_coverage_percent: float

    jupiter_checked: bool
    jupiter_status: str
    jupiter_tokens_checked: int
    jupiter_tokens_compatible: int
    jupiter_requests: int
    jupiter_compatibility_percent: float
    jupiter_results: list[dict]
    position_results: list[dict]

    started_at: datetime
    completed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
