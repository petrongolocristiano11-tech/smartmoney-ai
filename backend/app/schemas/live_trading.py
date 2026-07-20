from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


LiveTradingMode = Literal[
    "DISABLED",
    "DRY_RUN",
    "LIVE",
]

LiveSizingMode = Literal[
    "FIXED",
    "SOURCE_PERCENTAGE",
]


class LiveTradingPolicyUpdateRequest(
    BaseModel
):
    mode: LiveTradingMode | None = None

    confirmation: str | None = None

    kill_switch: bool | None = None

    stream_execution_enabled: (
        bool | None
    ) = None

    source_wallets: (
        list[str] | None
    ) = None

    buy_enabled: bool | None = None

    sell_enabled: bool | None = None

    sizing_mode: (
        LiveSizingMode | None
    ) = None

    fixed_buy_size_sol: (
        float | None
    ) = Field(
        default=None,
        gt=0,
    )

    source_trade_percentage: (
        float | None
    ) = Field(
        default=None,
        gt=0,
        le=100,
    )

    sell_position_percentage: (
        float | None
    ) = Field(
        default=None,
        gt=0,
        le=100,
    )

    max_order_size_sol: (
        float | None
    ) = Field(
        default=None,
        gt=0,
    )

    max_daily_buy_sol: (
        float | None
    ) = Field(
        default=None,
        gt=0,
    )

    max_daily_loss_sol: (
        float | None
    ) = Field(
        default=None,
        gt=0,
    )

    max_total_exposure_sol: (
        float | None
    ) = Field(
        default=None,
        gt=0,
    )

    min_wallet_reserve_sol: (
        float | None
    ) = Field(
        default=None,
        ge=0,
    )

    max_slippage_bps: (
        int | None
    ) = Field(
        default=None,
        ge=1,
        le=5000,
    )

    max_price_impact_percent: (
        float | None
    ) = Field(
        default=None,
        gt=0,
        le=100,
    )

    min_source_trade_sol: (
        float | None
    ) = Field(
        default=None,
        ge=0,
    )

    max_source_trade_age_seconds: (
        int | None
    ) = Field(
        default=None,
        ge=1,
        le=86400,
    )

    max_consecutive_failures: (
        int | None
    ) = Field(
        default=None,
        ge=1,
        le=100,
    )

    @field_validator(
        "source_wallets"
    )
    @classmethod
    def normalize_source_wallets(
        cls,
        value: list[str] | None,
    ):
        if value is None:
            return None

        normalized: list[str] = []
        seen: set[str] = set()

        for wallet in value:
            address = str(
                wallet
            ).strip()

            if not address:
                continue

            if not 32 <= len(
                address
            ) <= 44:
                raise ValueError(
                    "Wallet Solana non valido: "
                    f"{address}"
                )

            if address not in seen:
                normalized.append(
                    address
                )
                seen.add(
                    address
                )

        return normalized

    @model_validator(
        mode="after"
    )
    def validate_limits(
        self,
    ):
        if (
            self.fixed_buy_size_sol
            is not None
            and self.max_order_size_sol
            is not None
            and self.fixed_buy_size_sol
            > self.max_order_size_sol
        ):
            raise ValueError(
                "fixed_buy_size_sol non può "
                "superare max_order_size_sol."
            )

        if (
            self.max_order_size_sol
            is not None
            and self.max_daily_buy_sol
            is not None
            and self.max_order_size_sol
            > self.max_daily_buy_sol
        ):
            raise ValueError(
                "max_order_size_sol non può "
                "superare max_daily_buy_sol."
            )

        if (
            self.mode == "LIVE"
            and self.confirmation
            != "ENABLE LIVE TRADING"
        ):
            raise ValueError(
                "Per impostare LIVE usa "
                "confirmation="
                "'ENABLE LIVE TRADING'."
            )

        return self


class LiveTradingDryRunResetRequest(
    BaseModel
):
    confirmation: str

    source_wallets: list[str] = (
        Field(default_factory=list)
    )

    start_stream: bool = False

    buy_enabled: bool = True

    sell_enabled: bool = True

    @field_validator(
        "source_wallets"
    )
    @classmethod
    def normalize_source_wallets(
        cls,
        value: list[str],
    ) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()

        for wallet in value:
            address = str(
                wallet
            ).strip()

            if not address:
                continue

            if not 32 <= len(
                address
            ) <= 44:
                raise ValueError(
                    "Wallet Solana non valido: "
                    f"{address}"
                )

            if address not in seen:
                normalized.append(
                    address
                )
                seen.add(address)

        return normalized

    @model_validator(
        mode="after"
    )
    def validate_reset(
        self,
    ):
        if (
            self.confirmation
            != "RESET DRY RUN"
        ):
            raise ValueError(
                "Conferma non valida. "
                "Usa esattamente: "
                "RESET DRY RUN"
            )

        if (
            self.start_stream
            and not self.source_wallets
        ):
            raise ValueError(
                "Per avviare lo stream "
                "serve almeno un wallet."
            )

        return self


class LiveTradingDryRunCloseRequest(
    BaseModel
):
    confirmation: str

    @field_validator(
        "confirmation"
    )
    @classmethod
    def validate_confirmation(
        cls,
        value: str,
    ) -> str:
        normalized = str(value).strip()

        if (
            normalized
            != "CLOSE DRY RUN POSITION"
        ):
            raise ValueError(
                "Conferma non valida. "
                "Usa esattamente: "
                "CLOSE DRY RUN POSITION"
            )

        return normalized


class LiveTradingPolicyResponse(
    BaseModel
):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: int
    name: str
    mode: LiveTradingMode
    kill_switch: bool
    stream_execution_enabled: bool
    source_wallets: list[str]
    buy_enabled: bool
    sell_enabled: bool
    sizing_mode: LiveSizingMode
    fixed_buy_size_sol: float
    source_trade_percentage: float
    sell_position_percentage: float
    max_order_size_sol: float
    max_daily_buy_sol: float
    max_daily_loss_sol: float
    max_total_exposure_sol: float
    min_wallet_reserve_sol: float
    max_slippage_bps: int
    max_price_impact_percent: float
    min_source_trade_sol: float
    max_source_trade_age_seconds: int
    max_consecutive_failures: int
    consecutive_failures: int
    dry_run_generation: int
    dry_run_started_at: datetime | None
    created_at: datetime
    updated_at: datetime


class LivePositionResponse(
    BaseModel
):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: int

    mode: Literal[
        "DRY_RUN",
        "LIVE",
    ]

    generation: int

    token_mint: str

    status: Literal[
        "OPEN",
        "CLOSED",
    ]

    quantity_raw: Decimal
    cost_basis_sol: float
    realized_pnl_sol: float
    last_buy_signature: str | None
    last_sell_signature: str | None
    opened_at: datetime
    closed_at: datetime | None
    updated_at: datetime


class LiveCopyOrderResponse(
    BaseModel
):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: int
    idempotency_key: str
    source_trade_id: int | None
    source_signature: str
    source_wallet: str

    source_side: Literal[
        "BUY",
        "SELL",
    ]

    source_token_mint: str
    source_sol_amount: float | None
    source_token_amount: float | None

    mode: Literal[
        "DRY_RUN",
        "LIVE",
    ]

    generation: int

    status: Literal[
        "RECEIVED",
        "REJECTED",
        "DRY_RUN",
        "QUOTED",
        "SUBMITTED",
        "FILLED",
        "FAILED",
    ]

    input_mint: str
    output_mint: str
    requested_input_amount_raw: Decimal
    requested_value_sol: float
    expected_output_amount_raw: (
        Decimal | None
    )
    actual_input_amount_raw: (
        Decimal | None
    )
    actual_output_amount_raw: (
        Decimal | None
    )
    slippage_bps: int
    jupiter_request_id: str | None
    router: str | None
    transaction_signature: str | None
    error_code: str | None
    error_message: str | None
    realized_pnl_sol: float
    quoted_at: datetime | None
    submitted_at: datetime | None
    executed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class LiveTradingEventResponse(
    BaseModel
):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: int
    order_id: int | None
    event_type: str
    generation: int | None

    severity: Literal[
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ]

    message: str
    payload: dict | None
    created_at: datetime


class LiveTradingWorkerStatusResponse(
    BaseModel
):
    status: Literal[
        "STOPPED",
        "STARTING",
        "IDLE",
        "CONNECTING",
        "RUNNING",
        "DEGRADED",
        "ERROR",
    ]

    online: bool
    lease_active: bool
    worker_id: str | None
    lease_owner: str | None
    lease_expires_at: datetime | None
    active_wallets: list[str]
    monitored_wallets: int
    active_subscriptions: int
    queue_depth: int
    reconnect_count: int
    signatures_received: int
    signatures_processed: int
    signatures_failed: int
    signatures_dropped: int
    last_latency_ms: float | None
    config_fingerprint: str | None
    last_signature: str | None
    last_error_code: str | None
    last_error_message: str | None
    started_at: datetime | None
    heartbeat_at: datetime | None
    connected_at: datetime | None
    last_message_at: datetime | None
    last_trade_at: datetime | None
    last_error_at: datetime | None
    seconds_since_heartbeat: (
        float | None
    )
    updated_at: datetime


class LiveTradingStatusResponse(
    BaseModel
):
    policy: LiveTradingPolicyResponse

    worker: (
        LiveTradingWorkerStatusResponse
    )

    live_execution_configured: bool

    jupiter_configured: bool

    wallet_address: str | None

    wallet_balance_sol: float | None

    open_positions: int

    total_exposure_sol: float

    orders_today: int

    filled_orders_today: int

    realized_pnl_today_sol: float

    active_generation: int | None

    generation_started_at: (
        datetime | None
    )


class LiveTradingDryRunResetResponse(
    BaseModel
):
    policy: LiveTradingPolicyResponse
    previous_generation: int
    active_generation: int
    archived_positions: int
    archived_exposure_sol: float
    reset_at: datetime


class KillSwitchReleaseRequest(
    BaseModel
):
    confirmation: str

    @model_validator(
        mode="after"
    )
    def validate_confirmation(
        self,
    ):
        if (
            self.confirmation
            != "RELEASE LIVE TRADING"
        ):
            raise ValueError(
                "Conferma non valida. "
                "Usa esattamente: "
                "RELEASE LIVE TRADING"
            )

        return self


class LiveOrderListResponse(
    BaseModel
):
    count: int

    orders: list[
        LiveCopyOrderResponse
    ]


class LivePositionListResponse(
    BaseModel
):
    count: int

    positions: list[
        LivePositionResponse
    ]


class LiveEventListResponse(
    BaseModel
):
    count: int

    events: list[
        LiveTradingEventResponse
    ]