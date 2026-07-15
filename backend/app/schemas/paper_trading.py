from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


AccountStatus = Literal[
    "ACTIVE",
    "PAUSED",
    "STOPPED",
]


class PaperRequestModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class PaperAccountCreateRequest(
    PaperRequestModel
):
    name: str = Field(
        min_length=1,
        max_length=80,
    )

    starting_balance_sol: float = Field(
        default=10.0,
        gt=0,
        le=1_000_000,
    )

    max_position_size_sol: float = Field(
        default=0.5,
        gt=0,
        le=1_000_000,
    )

    max_open_positions: int = Field(
        default=3,
        ge=1,
        le=1_000,
    )

    daily_loss_limit_sol: float = Field(
        default=1.0,
        gt=0,
        le=1_000_000,
    )


class PaperAccountUpdateRequest(
    PaperRequestModel
):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
    )

    status: AccountStatus | None = None

    max_position_size_sol: (
        float | None
    ) = Field(
        default=None,
        gt=0,
        le=1_000_000,
    )

    max_open_positions: int | None = (
        Field(
            default=None,
            ge=1,
            le=1_000,
        )
    )

    daily_loss_limit_sol: (
        float | None
    ) = Field(
        default=None,
        gt=0,
        le=1_000_000,
    )

    @model_validator(mode="after")
    def require_update(
        self,
    ):
        if not self.model_fields_set:
            raise ValueError(
                "Specificare almeno una "
                "modifica."
            )

        return self


class PaperAccountResetRequest(
    PaperRequestModel
):
    confirmation_name: str = Field(
        min_length=1,
        max_length=80,
    )


class PaperBuyRequest(PaperRequestModel):
    token_mint: str = Field(
        min_length=1,
        max_length=64,
    )

    value_sol: float = Field(
        gt=0,
        le=1_000_000,
    )

    market_price_sol: float = Field(
        gt=0,
    )

    slippage_percent: float = Field(
        default=0.5,
        ge=0,
        le=50,
    )

    fee_percent: float = Field(
        default=0.25,
        ge=0,
        le=20,
    )

    signal_score: float | None = Field(
        default=None,
        ge=0,
        le=100,
    )

    reason: str | None = Field(
        default=None,
        max_length=500,
    )


class PaperSellRequest(
    PaperRequestModel
):
    token_mint: str = Field(
        min_length=1,
        max_length=64,
    )

    market_price_sol: float = Field(
        gt=0,
    )

    quantity: float | None = Field(
        default=None,
        gt=0,
    )

    slippage_percent: float = Field(
        default=0.5,
        ge=0,
        le=50,
    )

    fee_percent: float = Field(
        default=0.25,
        ge=0,
        le=20,
    )

    signal_score: float | None = Field(
        default=None,
        ge=0,
        le=100,
    )

    reason: str | None = Field(
        default=None,
        max_length=500,
    )


class PaperMarkRequest(
    PaperRequestModel
):
    token_mint: str = Field(
        min_length=1,
        max_length=64,
    )

    market_price_sol: float = Field(
        gt=0,
    )


class PaperResponseModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )


class PaperAccountResponse(
    PaperResponseModel
):
    id: int
    name: str
    status: AccountStatus

    starting_balance_sol: float
    cash_balance_sol: float
    realized_pnl_sol: float

    max_position_size_sol: float
    max_open_positions: int
    daily_loss_limit_sol: float

    created_at: datetime
    updated_at: datetime


class PaperPositionResponse(
    PaperResponseModel
):
    id: int
    account_id: int
    token_mint: str
    status: Literal["OPEN", "CLOSED"]

    quantity: float
    average_entry_price_sol: float
    cost_basis_sol: float
    last_price_sol: float
    market_value_sol: float

    unrealized_pnl_sol: float
    realized_pnl_sol: float

    opened_at: datetime
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PaperOrderResponse(
    PaperResponseModel
):
    id: int
    account_id: int
    position_id: int | None
    token_mint: str

    side: Literal["BUY", "SELL"]
    status: Literal[
        "PENDING",
        "FILLED",
        "REJECTED",
    ]

    requested_value_sol: float
    quantity: float
    execution_price_sol: float
    gross_value_sol: float
    fee_sol: float
    slippage_percent: float
    realized_pnl_sol: float

    signal_score: float | None
    reason: str | None

    executed_at: datetime | None
    created_at: datetime


class PaperAccountSummaryResponse(
    BaseModel
):
    account_id: int
    name: str
    status: AccountStatus

    starting_balance_sol: float
    cash_balance_sol: float
    market_value_sol: float
    equity_sol: float

    realized_pnl_sol: float
    unrealized_pnl_sol: float

    daily_realized_pnl_sol: float
    daily_loss_used_sol: float
    daily_loss_limit_sol: float

    total_return_percent: float

    open_positions: int
    max_open_positions: int
    max_position_size_sol: float


class PaperAccountListItem(
    BaseModel
):
    account: PaperAccountResponse
    summary: PaperAccountSummaryResponse


class PaperAccountListResponse(
    BaseModel
):
    count: int
    accounts: list[
        PaperAccountListItem
    ]


class PaperAccountDetailResponse(
    BaseModel
):
    account: PaperAccountResponse
    summary: PaperAccountSummaryResponse
    positions: list[
        PaperPositionResponse
    ]
    orders: list[
        PaperOrderResponse
    ]


class PaperExecutionResponse(
    BaseModel
):
    account: PaperAccountResponse
    position: PaperPositionResponse
    order: PaperOrderResponse
    summary: PaperAccountSummaryResponse 