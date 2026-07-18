from dataclasses import dataclass
from datetime import (
    datetime,
    time,
    timezone,
)
from decimal import (
    Decimal,
    ROUND_DOWN,
)

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.core.constants import (
    SOL_MINT,
)
from backend.app.models.live_copy_order import (
    LiveCopyOrder,
)
from backend.app.models.live_position import (
    LivePosition,
)
from backend.app.models.live_trading_policy import (
    LiveTradingPolicy,
)
from backend.app.models.trade import Trade
from backend.app.services.live_trading_errors import (
    LiveTradingError,
)


LAMPORTS_PER_SOL = 1_000_000_000

ACTIVE_ORDER_STATUSES = {
    "RECEIVED",
    "QUOTED",
    "SUBMITTED",
    "DRY_RUN",
    "FILLED",
}


@dataclass(frozen=True)
class LiveExecutionPlan:
    side: str
    token_mint: str
    input_mint: str
    output_mint: str
    input_amount_raw: int
    requested_value_sol: float
    position_id: int | None


def utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


def utc_day_start(
    now: datetime | None = None,
) -> datetime:
    value = now or utc_now()

    if value.tzinfo is None:
        value = value.replace(
            tzinfo=timezone.utc
        )

    return datetime.combine(
        value.date(),
        time.min,
        tzinfo=timezone.utc,
    )


def _as_utc(
    value: datetime | None,
) -> datetime | None:
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(
        timezone.utc
    )


def get_total_exposure_sol(
    db: Session,
    *,
    mode: str,
) -> float:
    value = (
        db.query(
            func.coalesce(
                func.sum(
                    LivePosition
                    .cost_basis_sol
                ),
                0.0,
            )
        )
        .filter(
            LivePosition.status
            == "OPEN",
            LivePosition.mode
            == mode,
        )
        .scalar()
    )

    return float(
        value or 0.0
    )


def get_daily_buy_sol(
    db: Session,
    *,
    mode: str,
    current_order_id: int | None = None,
    now: datetime | None = None,
) -> float:
    query = db.query(
        func.coalesce(
            func.sum(
                LiveCopyOrder
                .requested_value_sol
            ),
            0.0,
        )
    ).filter(
        LiveCopyOrder.created_at
        >= utc_day_start(now),
        LiveCopyOrder.source_side
        == "BUY",
        LiveCopyOrder.mode
        == mode,
        LiveCopyOrder.status.in_(
            ACTIVE_ORDER_STATUSES
        ),
    )

    if current_order_id is not None:
        query = query.filter(
            LiveCopyOrder.id
            != current_order_id
        )

    return float(
        query.scalar() or 0.0
    )


def get_realized_pnl_today_sol(
    db: Session,
    *,
    mode: str | None = None,
    now: datetime | None = None,
) -> float:
    query = db.query(
        func.coalesce(
            func.sum(
                LiveCopyOrder
                .realized_pnl_sol
            ),
            0.0,
        )
    ).filter(
        LiveCopyOrder.created_at
        >= utc_day_start(now),
        LiveCopyOrder.status.in_(
            (
                "DRY_RUN",
                "FILLED",
            )
        ),
    )

    if mode is not None:
        query = query.filter(
            LiveCopyOrder.mode
            == mode
        )

    value = query.scalar()

    return float(
        value or 0.0
    )


def _reject(
    message: str,
    code: str,
    status_code: int = 409,
) -> None:
    raise LiveTradingError(
        message,
        code=code,
        status_code=status_code,
    )


def build_live_execution_plan(
    db: Session,
    *,
    policy: LiveTradingPolicy,
    trade: Trade,
    wallet_balance_sol: float | None,
    current_order_id: int | None = None,
    now: datetime | None = None,
) -> LiveExecutionPlan:
    now = now or utc_now()

    side = str(
        trade.side or ""
    ).strip().upper()

    token_mint = str(
        trade.token_mint or ""
    ).strip()

    source_wallet = str(
        trade.wallet_address or ""
    ).strip()

    source_sol_amount = float(
        trade.sol_amount or 0.0
    )

    if policy.mode == "DISABLED":
        _reject(
            "Live Trading disabilitato.",
            "LIVE_TRADING_DISABLED",
        )

    if policy.kill_switch:
        _reject(
            "Kill switch Live Trading "
            "attivo.",
            "KILL_SWITCH_ACTIVE",
        )

    if side not in {
        "BUY",
        "SELL",
    }:
        _reject(
            "Il trade sorgente non è "
            "BUY o SELL.",
            "UNSUPPORTED_SOURCE_SIDE",
            422,
        )

    if (
        not token_mint
        or token_mint == SOL_MINT
    ):
        _reject(
            "Token mint sorgente non valido.",
            "INVALID_SOURCE_TOKEN",
            422,
        )

    if (
        source_wallet
        not in set(
            policy.source_wallets
            or []
        )
    ):
        _reject(
            "Wallet sorgente non presente "
            "nella allowlist.",
            "SOURCE_WALLET_NOT_ALLOWED",
            403,
        )

    if (
        side == "BUY"
        and not policy.buy_enabled
    ):
        _reject(
            "Copy BUY disabilitati "
            "dalla policy.",
            "BUY_DISABLED",
        )

    if (
        side == "SELL"
        and not policy.sell_enabled
    ):
        _reject(
            "Copy SELL disabilitati "
            "dalla policy.",
            "SELL_DISABLED",
        )

    source_time = _as_utc(
        trade.block_time
        or trade.created_at
    )

    if source_time is not None:
        age_seconds = max(
            0.0,
            (
                now - source_time
            ).total_seconds(),
        )

        if (
            age_seconds
            > policy
            .max_source_trade_age_seconds
        ):
            _reject(
                "Trade sorgente troppo "
                "vecchio per essere copiato.",
                "SOURCE_TRADE_EXPIRED",
            )

    if (
        source_sol_amount
        < policy.min_source_trade_sol
    ):
        _reject(
            "Trade sorgente inferiore "
            "alla dimensione minima "
            "configurata.",
            "SOURCE_TRADE_TOO_SMALL",
        )

    realized_today = (
        get_realized_pnl_today_sol(
            db,
            mode=policy.mode,
            now=now,
        )
    )

    if (
        realized_today
        <= -abs(
            policy.max_daily_loss_sol
        )
    ):
        _reject(
            "Limite di perdita "
            "giornaliera raggiunto.",
            "DAILY_LOSS_LIMIT",
        )

    if side == "BUY":
        if (
            policy.sizing_mode
            == "FIXED"
        ):
            requested_value_sol = float(
                policy.fixed_buy_size_sol
            )

        else:
            requested_value_sol = (
                source_sol_amount
                * (
                    float(
                        policy
                        .source_trade_percentage
                    )
                    / 100.0
                )
            )

        if requested_value_sol <= 0:
            _reject(
                "Dimensione BUY non valida.",
                "INVALID_ORDER_SIZE",
                422,
            )

        if (
            requested_value_sol
            > policy.max_order_size_sol
        ):
            _reject(
                "Ordine superiore al limite "
                "massimo per singola "
                "operazione.",
                "MAX_ORDER_SIZE",
            )

        daily_buy = get_daily_buy_sol(
            db,
            mode=policy.mode,
            current_order_id=(
                current_order_id
            ),
            now=now,
        )

        if (
            daily_buy
            + requested_value_sol
            > policy.max_daily_buy_sol
        ):
            _reject(
                "Limite massimo di acquisti "
                "giornalieri superato.",
                "MAX_DAILY_BUY",
            )

        exposure = (
            get_total_exposure_sol(
                db,
                mode=policy.mode,
            )
        )

        if (
            exposure
            + requested_value_sol
            > policy
            .max_total_exposure_sol
        ):
            _reject(
                "Esposizione massima "
                "Live Trading superata.",
                "MAX_TOTAL_EXPOSURE",
            )

        if policy.mode == "LIVE":
            if wallet_balance_sol is None:
                _reject(
                    "Saldo wallet Live Trading "
                    "non disponibile.",
                    "WALLET_BALANCE_UNAVAILABLE",
                    503,
                )

            required_balance = (
                requested_value_sol
                + policy
                .min_wallet_reserve_sol
            )

            if (
                wallet_balance_sol
                < required_balance
            ):
                _reject(
                    "Saldo wallet insufficiente "
                    "mantenendo la riserva "
                    "minima SOL.",
                    "INSUFFICIENT_WALLET_BALANCE",
                )

        amount_raw = int(
            (
                Decimal(
                    str(
                        requested_value_sol
                    )
                )
                * LAMPORTS_PER_SOL
            ).quantize(
                Decimal("1"),
                rounding=ROUND_DOWN,
            )
        )

        if amount_raw <= 0:
            _reject(
                "Importo BUY in lamport "
                "non valido.",
                "INVALID_ORDER_AMOUNT",
                422,
            )

        return LiveExecutionPlan(
            side=side,
            token_mint=token_mint,
            input_mint=SOL_MINT,
            output_mint=token_mint,
            input_amount_raw=amount_raw,
            requested_value_sol=(
                requested_value_sol
            ),
            position_id=None,
        )

    position = (
        db.query(LivePosition)
        .filter(
            LivePosition.mode
            == policy.mode,
            LivePosition.token_mint
            == token_mint,
            LivePosition.status
            == "OPEN",
        )
        .with_for_update()
        .first()
    )

    if (
        position is None
        or Decimal(
            position.quantity_raw or 0
        ) <= 0
    ):
        _reject(
            "Nessuna posizione aperta "
            "da vendere.",
            "POSITION_NOT_FOUND",
            404,
        )

    quantity_raw = Decimal(
        position.quantity_raw
    )

    input_amount = int(
        (
            quantity_raw
            * Decimal(
                str(
                    policy
                    .sell_position_percentage
                )
            )
            / Decimal("100")
        ).quantize(
            Decimal("1"),
            rounding=ROUND_DOWN,
        )
    )

    input_amount = min(
        input_amount,
        int(quantity_raw),
    )

    if input_amount <= 0:
        _reject(
            "Quantità SELL calcolata "
            "non valida.",
            "INVALID_ORDER_AMOUNT",
            422,
        )

    cost_fraction = float(
        Decimal(input_amount)
        / quantity_raw
    )

    requested_value_sol = max(
        0.0,
        float(
            position.cost_basis_sol
        )
        * cost_fraction,
    )

    return LiveExecutionPlan(
        side=side,
        token_mint=token_mint,
        input_mint=token_mint,
        output_mint=SOL_MINT,
        input_amount_raw=input_amount,
        requested_value_sol=(
            requested_value_sol
        ),
        position_id=position.id,
    ) 