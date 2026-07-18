import hashlib
from datetime import (
    datetime,
    timezone,
)
from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import (
    IntegrityError,
)
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.constants import (
    SOL_MINT,
)
from backend.app.models.live_copy_order import (
    LiveCopyOrder,
)
from backend.app.models.live_position import (
    LivePosition,
)
from backend.app.models.live_trading_event import (
    LiveTradingEvent,
)
from backend.app.models.live_trading_policy import (
    LiveTradingPolicy,
)
from backend.app.models.trade import Trade
from backend.app.services.jupiter_swap_client import (
    JupiterSwapClient,
    JupiterSwapError,
    sanitize_jupiter_payload,
)
from backend.app.services.live_trading_errors import (
    LiveTradingError,
    SolanaRpcError,
    SolanaSignerError,
)
from backend.app.services.live_trading_policy_service import (
    engage_kill_switch,
    get_or_create_live_policy,
    record_live_event,
)
from backend.app.services.live_trading_risk_engine import (
    LAMPORTS_PER_SOL,
    LiveExecutionPlan,
    build_live_execution_plan,
    get_realized_pnl_today_sol,
    get_total_exposure_sol,
    utc_day_start,
)
from backend.app.services.solana_rpc import (
    SolanaRpcClient,
)
from backend.app.services.solana_transaction_signer import (
    SolanaTransactionSigner,
)


def utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


def build_idempotency_key(
    trade: Trade,
) -> str:
    material = "|".join(
        (
            str(
                trade.signature or ""
            ).strip(),
            str(
                trade.wallet_address or ""
            ).strip(),
            str(
                trade.side or ""
            ).strip().upper(),
            str(
                trade.token_mint or ""
            ).strip(),
        )
    )

    return hashlib.sha256(
        material.encode("utf-8")
    ).hexdigest()


def _basic_trade_values(
    trade: Trade,
) -> tuple[
    str,
    str,
    str,
    str,
]:
    side = str(
        trade.side or ""
    ).strip().upper()

    token_mint = str(
        trade.token_mint or ""
    ).strip()

    source_wallet = str(
        trade.wallet_address or ""
    ).strip()

    signature = str(
        trade.signature or ""
    ).strip()

    if side not in {
        "BUY",
        "SELL",
    }:
        raise LiveTradingError(
            "Il trade sorgente non è "
            "BUY o SELL.",
            code="UNSUPPORTED_SOURCE_SIDE",
            status_code=422,
        )

    if (
        not token_mint
        or token_mint == SOL_MINT
    ):
        raise LiveTradingError(
            "Token mint sorgente non valido.",
            code="INVALID_SOURCE_TOKEN",
            status_code=422,
        )

    if (
        not source_wallet
        or not signature
    ):
        raise LiveTradingError(
            "Trade sorgente incompleto.",
            code="INVALID_SOURCE_TRADE",
            status_code=422,
        )

    input_mint = (
        SOL_MINT
        if side == "BUY"
        else token_mint
    )

    output_mint = (
        token_mint
        if side == "BUY"
        else SOL_MINT
    )

    return (
        side,
        token_mint,
        input_mint,
        output_mint,
    )


def _get_locked_policy(
    db: Session,
) -> LiveTradingPolicy:
    get_or_create_live_policy(
        db
    )

    return (
        db.query(
            LiveTradingPolicy
        )
        .filter(
            LiveTradingPolicy.name
            == "default"
        )
        .with_for_update()
        .one()
    )


def _claim_order(
    db: Session,
    *,
    trade: Trade,
    policy: LiveTradingPolicy,
) -> tuple[
    LiveCopyOrder,
    bool,
]:
    idempotency_key = (
        build_idempotency_key(
            trade
        )
    )

    existing = (
        db.query(LiveCopyOrder)
        .filter(
            LiveCopyOrder.idempotency_key
            == idempotency_key
        )
        .first()
    )

    if existing is not None:
        return existing, False

    (
        side,
        token_mint,
        input_mint,
        output_mint,
    ) = _basic_trade_values(
        trade
    )

    order = LiveCopyOrder(
        idempotency_key=idempotency_key,
        source_trade_id=trade.id,
        source_signature=trade.signature,
        source_wallet=(
            trade.wallet_address
        ),
        source_side=side,
        source_token_mint=token_mint,
        source_sol_amount=(
            trade.sol_amount
        ),
        source_token_amount=(
            trade.token_amount
        ),
        mode=policy.mode,
        status="RECEIVED",
        input_mint=input_mint,
        output_mint=output_mint,
        requested_input_amount_raw=(
            Decimal(0)
        ),
        requested_value_sol=0.0,
        slippage_bps=(
            policy.max_slippage_bps
        ),
    )

    db.add(order)

    try:
        db.commit()

    except IntegrityError:
        db.rollback()

        existing = (
            db.query(LiveCopyOrder)
            .filter(
                LiveCopyOrder
                .idempotency_key
                == idempotency_key
            )
            .one()
        )

        return existing, False

    db.refresh(order)

    return order, True


def _get_position_for_update(
    db: Session,
    *,
    mode: str,
    token_mint: str,
) -> LivePosition | None:
    return (
        db.query(LivePosition)
        .filter(
            LivePosition.mode == mode,
            LivePosition.token_mint
            == token_mint,
        )
        .with_for_update()
        .first()
    )


def _apply_filled_position(
    db: Session,
    *,
    order: LiveCopyOrder,
    plan: LiveExecutionPlan,
    input_amount_raw: int,
    output_amount_raw: int,
    execution_signature: str,
) -> float:
    now = utc_now()

    position = (
        _get_position_for_update(
            db,
            mode=order.mode,
            token_mint=(
                plan.token_mint
            ),
        )
    )

    if plan.side == "BUY":
        if position is None:
            position = LivePosition(
                mode=order.mode,
                token_mint=(
                    plan.token_mint
                ),
                status="OPEN",
                quantity_raw=Decimal(0),
                cost_basis_sol=0.0,
                realized_pnl_sol=0.0,
            )

            db.add(position)

        elif position.status == "CLOSED":
            position.status = "OPEN"

            position.quantity_raw = (
                Decimal(0)
            )

            position.cost_basis_sol = 0.0

            position.opened_at = now
            position.closed_at = None

        position.quantity_raw = (
            Decimal(
                position.quantity_raw
                or 0
            )
            + Decimal(
                output_amount_raw
            )
        )

        position.cost_basis_sol = (
            float(
                position.cost_basis_sol
                or 0.0
            )
            + (
                float(
                    input_amount_raw
                )
                / LAMPORTS_PER_SOL
            )
        )

        position.last_buy_signature = (
            execution_signature
        )

        return 0.0

    if (
        position is None
        or Decimal(
            position.quantity_raw
            or 0
        ) <= 0
    ):
        raise LiveTradingError(
            "Posizione scomparsa prima "
            "dell'aggiornamento SELL.",
            code="POSITION_NOT_FOUND",
            status_code=409,
        )

    previous_quantity = Decimal(
        position.quantity_raw
    )

    sold_quantity = min(
        Decimal(input_amount_raw),
        previous_quantity,
    )

    sold_fraction = float(
        sold_quantity
        / previous_quantity
    )

    removed_cost_basis = (
        float(
            position.cost_basis_sol
            or 0.0
        )
        * sold_fraction
    )

    proceeds_sol = (
        float(output_amount_raw)
        / LAMPORTS_PER_SOL
    )

    realized_pnl = (
        proceeds_sol
        - removed_cost_basis
    )

    remaining_quantity = (
        previous_quantity
        - sold_quantity
    )

    position.quantity_raw = (
        remaining_quantity
    )

    position.cost_basis_sol = max(
        0.0,
        float(
            position.cost_basis_sol
            or 0.0
        )
        - removed_cost_basis,
    )

    position.realized_pnl_sol = (
        float(
            position.realized_pnl_sol
            or 0.0
        )
        + realized_pnl
    )

    position.last_sell_signature = (
        execution_signature
    )

    if remaining_quantity <= 0:
        position.quantity_raw = (
            Decimal(0)
        )

        position.cost_basis_sol = 0.0
        position.status = "CLOSED"
        position.closed_at = now

    return realized_pnl


def _is_technical_failure(
    error: LiveTradingError,
) -> bool:
    return isinstance(
        error,
        (
            JupiterSwapError,
            SolanaSignerError,
            SolanaRpcError,
        ),
    ) or (
        error.code
        == "LIVE_EXECUTION_INTERNAL_ERROR"
    )


def _finalize_error(
    db: Session,
    *,
    order_id: int,
    error: LiveTradingError,
) -> LiveCopyOrder:
    db.rollback()

    order = (
        db.query(LiveCopyOrder)
        .filter(
            LiveCopyOrder.id
            == order_id
        )
        .one()
    )

    policy = _get_locked_policy(
        db
    )

    technical_failure = (
        _is_technical_failure(
            error
        )
    )

    order.status = (
        "FAILED"
        if technical_failure
        else "REJECTED"
    )

    order.error_code = error.code
    order.error_message = error.message

    if error.payload:
        order.execute_response = dict(
            error.payload
        )

    record_live_event(
        db,
        order_id=order.id,
        event_type=(
            "ORDER_FAILED"
            if technical_failure
            else "ORDER_REJECTED"
        ),
        severity=(
            "ERROR"
            if technical_failure
            else "WARNING"
        ),
        message=error.message,
        payload={
            "code": error.code,
        },
    )

    if technical_failure:
        policy.consecutive_failures = (
            int(
                policy
                .consecutive_failures
                or 0
            )
            + 1
        )

        if (
            policy.consecutive_failures
            >= policy
            .max_consecutive_failures
        ):
            engage_kill_switch(
                db,
                policy,
                reason=(
                    "Kill switch automatico: "
                    "raggiunto il limite di "
                    f"{policy.max_consecutive_failures} "
                    "errori consecutivi."
                ),
                automatic=True,
                commit=False,
            )

    db.commit()
    db.refresh(order)

    return order


def execute_source_trade(
    db: Session,
    *,
    trade: Trade,
    origin: str = "MANUAL",
    jupiter_client: (
        JupiterSwapClient | None
    ) = None,
    rpc_client: (
        SolanaRpcClient | None
    ) = None,
    signer: (
        SolanaTransactionSigner
        | None
    ) = None,
) -> LiveCopyOrder | None:
    normalized_origin = str(
        origin or "MANUAL"
    ).strip().upper()

    if normalized_origin not in {
        "MANUAL",
        "STREAM",
    }:
        raise LiveTradingError(
            "Origin deve essere "
            "MANUAL o STREAM.",
            code="INVALID_EXECUTION_ORIGIN",
            status_code=422,
        )

    policy = get_or_create_live_policy(
        db
    )

    if (
        normalized_origin == "STREAM"
        and (
            policy.mode == "DISABLED"
            or not (
                policy
                .stream_execution_enabled
            )
        )
    ):
        return None

    if policy.mode == "DISABLED":
        raise LiveTradingError(
            "Live Trading disabilitato.",
            code="LIVE_TRADING_DISABLED",
            status_code=409,
        )

    order, claimed = _claim_order(
        db,
        trade=trade,
        policy=policy,
    )

    if not claimed:
        return order

    try:
        policy = _get_locked_policy(
            db
        )

        order = (
            db.query(LiveCopyOrder)
            .filter(
                LiveCopyOrder.id
                == order.id
            )
            .with_for_update()
            .one()
        )

        order.mode = policy.mode

        order.slippage_bps = (
            policy.max_slippage_bps
        )

        wallet_balance_sol: (
            float | None
        ) = None

        if policy.mode == "LIVE":
            if not (
                settings
                .is_live_trading_configured
            ):
                raise LiveTradingError(
                    "Esecuzione LIVE non "
                    "configurata completamente.",
                    code=(
                        "LIVE_EXECUTION_NOT_CONFIGURED"
                    ),
                    status_code=503,
                )

            rpc_client = (
                rpc_client
                or SolanaRpcClient()
            )

            wallet_balance_sol = (
                rpc_client
                .get_balance_sol(
                    settings
                    .LIVE_TRADING_WALLET_ADDRESS
                )
            )

        plan = build_live_execution_plan(
            db,
            policy=policy,
            trade=trade,
            wallet_balance_sol=(
                wallet_balance_sol
            ),
            current_order_id=order.id,
        )

        order.input_mint = (
            plan.input_mint
        )

        order.output_mint = (
            plan.output_mint
        )

        order.requested_input_amount_raw = (
            Decimal(
                plan.input_amount_raw
            )
        )

        order.requested_value_sol = (
            plan.requested_value_sol
        )

        jupiter_client = (
            jupiter_client
            or JupiterSwapClient()
        )

        taker = (
            settings
            .LIVE_TRADING_WALLET_ADDRESS
            if policy.mode == "LIVE"
            else None
        )

        quote = (
            jupiter_client
            .get_order(
                input_mint=(
                    plan.input_mint
                ),
                output_mint=(
                    plan.output_mint
                ),
                amount_raw=(
                    plan.input_amount_raw
                ),
                taker=taker,
                slippage_bps=(
                    policy
                    .max_slippage_bps
                ),
            )
        )

        if (
            quote.slippage_bps
            > policy.max_slippage_bps
        ):
            raise LiveTradingError(
                "Slippage Jupiter superiore "
                "al limite configurato.",
                code="MAX_SLIPPAGE_EXCEEDED",
                status_code=409,
            )

        if (
            quote.price_impact_percent
            > policy
            .max_price_impact_percent
        ):
            raise LiveTradingError(
                "Price impact Jupiter "
                "superiore al limite "
                "configurato.",
                code="MAX_PRICE_IMPACT_EXCEEDED",
                status_code=409,
                payload={
                    "price_impact_percent":
                        quote
                        .price_impact_percent,
                },
            )

        now = utc_now()

        order.status = "QUOTED"

        order.jupiter_request_id = (
            quote.request_id
        )

        order.router = quote.router

        order.expected_output_amount_raw = (
            Decimal(
                quote.out_amount
            )
        )

        order.order_response = (
            sanitize_jupiter_payload(
                quote.raw
            )
        )

        order.quoted_at = now

        if policy.mode == "DRY_RUN":
            dry_signature = (
                "DRY_RUN:"
                f"{trade.signature}"
            )

            order.actual_input_amount_raw = (
                Decimal(
                    quote.in_amount
                )
            )

            order.actual_output_amount_raw = (
                Decimal(
                    quote.out_amount
                )
            )

            order.realized_pnl_sol = (
                _apply_filled_position(
                    db,
                    order=order,
                    plan=plan,
                    input_amount_raw=(
                        quote.in_amount
                    ),
                    output_amount_raw=(
                        quote.out_amount
                    ),
                    execution_signature=(
                        dry_signature
                    ),
                )
            )

            order.status = "DRY_RUN"
            order.executed_at = now

            policy.consecutive_failures = 0

            record_live_event(
                db,
                order_id=order.id,
                event_type=(
                    "DRY_RUN_COMPLETED"
                ),
                message=(
                    "Ordine copy-trading "
                    "simulato con quotazione "
                    "Jupiter."
                ),
                payload={
                    "side":
                        plan.side,
                    "token_mint":
                        plan.token_mint,
                    "router":
                        quote.router,
                },
            )

            db.commit()
            db.refresh(order)

            return order

        signer = (
            signer
            or SolanaTransactionSigner()
        )

        if not quote.transaction:
            raise JupiterSwapError(
                "Jupiter non ha restituito "
                "la transazione da firmare.",
                code=(
                    "JUPITER_TRANSACTION_MISSING"
                ),
                status_code=502,
            )

        signed_transaction = (
            signer
            .sign_base64_versioned_transaction(
                quote.transaction
            )
        )

        order.status = "SUBMITTED"

        order.submitted_at = utc_now()

        execution = (
            jupiter_client
            .execute_order(
                signed_transaction=(
                    signed_transaction
                ),
                request_id=(
                    quote.request_id
                ),
                last_valid_block_height=(
                    quote
                    .last_valid_block_height
                ),
            )
        )

        order.execute_response = (
            sanitize_jupiter_payload(
                execution.raw
            )
        )

        order.transaction_signature = (
            execution.signature
        )

        if not execution.success:
            raise JupiterSwapError(
                execution.error
                or (
                    "Jupiter non ha "
                    "confermato l'operazione."
                ),
                code=(
                    "JUPITER_EXECUTION_FAILED"
                ),
                status_code=502,
                payload={
                    "jupiter_code":
                        execution.code,
                    "signature":
                        execution.signature,
                },
            )

        actual_input = (
            execution.input_amount
            or quote.in_amount
        )

        actual_output = (
            execution.output_amount
            or quote.out_amount
        )

        execution_signature = (
            execution.signature
            or trade.signature
        )

        order.actual_input_amount_raw = (
            Decimal(
                actual_input
            )
        )

        order.actual_output_amount_raw = (
            Decimal(
                actual_output
            )
        )

        order.realized_pnl_sol = (
            _apply_filled_position(
                db,
                order=order,
                plan=plan,
                input_amount_raw=(
                    actual_input
                ),
                output_amount_raw=(
                    actual_output
                ),
                execution_signature=(
                    execution_signature
                ),
            )
        )

        order.status = "FILLED"

        order.executed_at = utc_now()

        policy.consecutive_failures = 0

        record_live_event(
            db,
            order_id=order.id,
            event_type="ORDER_FILLED",
            message=(
                "Ordine copy-trading "
                "eseguito e confermato."
            ),
            payload={
                "side":
                    plan.side,
                "token_mint":
                    plan.token_mint,
                "signature":
                    execution.signature,
                "router":
                    quote.router,
            },
        )

        db.commit()
        db.refresh(order)

        return order

    except LiveTradingError as error:
        return _finalize_error(
            db,
            order_id=order.id,
            error=error,
        )

    except Exception as exception:
        error = LiveTradingError(
            "Errore interno durante "
            "l'esecuzione copy-trading.",
            code=(
                "LIVE_EXECUTION_INTERNAL_ERROR"
            ),
            status_code=500,
            payload={
                "error_type":
                    type(
                        exception
                    ).__name__,
            },
        )

        return _finalize_error(
            db,
            order_id=order.id,
            error=error,
        )


def get_live_trading_status(
    db: Session,
    *,
    rpc_client: (
        SolanaRpcClient | None
    ) = None,
) -> dict[str, Any]:
    policy = get_or_create_live_policy(
        db
    )

    mode_filter = (
        policy.mode
        if policy.mode in {
            "DRY_RUN",
            "LIVE",
        }
        else None
    )

    positions_query = (
        db.query(LivePosition)
        .filter(
            LivePosition.status
            == "OPEN"
        )
    )

    if mode_filter:
        positions_query = (
            positions_query.filter(
                LivePosition.mode
                == mode_filter
            )
        )

    open_positions = (
        positions_query.count()
    )

    if mode_filter:
        total_exposure = (
            get_total_exposure_sol(
                db,
                mode=mode_filter,
            )
        )

    else:
        total_exposure = float(
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
                == "OPEN"
            )
            .scalar()
            or 0.0
        )

    today = utc_day_start()

    orders_today = (
        db.query(LiveCopyOrder)
        .filter(
            LiveCopyOrder.created_at
            >= today
        )
        .count()
    )

    filled_orders_today = (
        db.query(LiveCopyOrder)
        .filter(
            LiveCopyOrder.created_at
            >= today,
            LiveCopyOrder.status.in_(
                (
                    "DRY_RUN",
                    "FILLED",
                )
            ),
        )
        .count()
    )

    wallet_balance_sol: (
        float | None
    ) = None

    if (
        settings
        .LIVE_TRADING_WALLET_ADDRESS
    ):
        try:
            wallet_balance_sol = (
                (
                    rpc_client
                    or SolanaRpcClient()
                )
                .get_balance_sol(
                    settings
                    .LIVE_TRADING_WALLET_ADDRESS
                )
            )

        except LiveTradingError:
            wallet_balance_sol = None

    return {
        "policy": policy,
        "live_execution_configured":
            settings
            .is_live_trading_configured,
        "jupiter_configured":
            bool(
                settings
                .JUPITER_API_KEY
            ),
        "wallet_address":
            (
                settings
                .LIVE_TRADING_WALLET_ADDRESS
                or None
            ),
        "wallet_balance_sol":
            wallet_balance_sol,
        "open_positions":
            open_positions,
        "total_exposure_sol":
            total_exposure,
        "orders_today":
            orders_today,
        "filled_orders_today":
            filled_orders_today,
        "realized_pnl_today_sol":
            get_realized_pnl_today_sol(
                db,
                mode=mode_filter,
            ),
    }


def list_live_orders(
    db: Session,
    *,
    limit: int = 100,
    status: str | None = None,
    mode: str | None = None,
) -> list[LiveCopyOrder]:
    query = db.query(
        LiveCopyOrder
    )

    if status:
        query = query.filter(
            LiveCopyOrder.status
            == status.upper()
        )

    if mode:
        query = query.filter(
            LiveCopyOrder.mode
            == mode.upper()
        )

    return (
        query
        .order_by(
            LiveCopyOrder
            .created_at
            .desc()
        )
        .limit(
            max(
                1,
                min(
                    limit,
                    500,
                ),
            )
        )
        .all()
    )


def list_live_positions(
    db: Session,
    *,
    status: str | None = None,
    mode: str | None = None,
) -> list[LivePosition]:
    query = db.query(
        LivePosition
    )

    if status:
        query = query.filter(
            LivePosition.status
            == status.upper()
        )

    if mode:
        query = query.filter(
            LivePosition.mode
            == mode.upper()
        )

    return (
        query
        .order_by(
            LivePosition
            .updated_at
            .desc()
        )
        .all()
    )


def list_live_events(
    db: Session,
    *,
    limit: int = 200,
) -> list[LiveTradingEvent]:
    return (
        db.query(
            LiveTradingEvent
        )
        .order_by(
            LiveTradingEvent
            .created_at
            .desc()
        )
        .limit(
            max(
                1,
                min(
                    limit,
                    1000,
                ),
            )
        )
        .all()
    ) 