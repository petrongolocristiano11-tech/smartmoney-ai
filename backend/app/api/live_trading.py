from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy.orm import Session

from backend.app.core.live_trading_security import (
    require_live_trading_key,
)
from backend.app.database.session import (
    get_db,
)
from backend.app.models.trade import Trade
from backend.app.schemas.live_trading import (
    KillSwitchReleaseRequest,
    LiveCopyOrderResponse,
    LiveTradingDryRunCloseRequest,
    LiveTradingDryRunResetRequest,
    LiveTradingDryRunResetResponse,
    LiveEventListResponse,
    LiveOrderListResponse,
    LivePositionListResponse,
    LiveTradingPolicyResponse,
    LiveTradingPolicyUpdateRequest,
    LiveTradingStatusResponse,
    LiveTradingWorkerStatusResponse,
)
from backend.app.services.jupiter_swap_client import (
    JupiterSwapClient,
)
from backend.app.services.live_copy_trading_engine import (
    close_dry_run_position,
    execute_source_trade,
    get_live_trading_status,
    list_live_events,
    list_live_orders,
    list_live_positions,
)
from backend.app.services.live_trading_errors import (
    LiveTradingError,
)
from backend.app.services.live_trading_policy_service import (
    engage_kill_switch,
    get_or_create_live_policy,
    release_kill_switch,
    update_live_policy,
)
from backend.app.services.live_trading_reset_service import (
    reset_dry_run_generation,
)
from backend.app.services.live_trading_worker_state import (
    get_live_worker_status,
)
from backend.app.services.solana_rpc import (
    SolanaRpcClient,
)
from backend.app.services.solana_transaction_signer import (
    SolanaTransactionSigner,
)


router = APIRouter(
    prefix="/live-trading",
    tags=["Live Trading"],
    dependencies=[
        Depends(
            require_live_trading_key
        )
    ],
)


def get_jupiter_client() -> JupiterSwapClient:
    return JupiterSwapClient()


def get_solana_rpc_client() -> SolanaRpcClient:
    return SolanaRpcClient()


def get_transaction_signer() -> SolanaTransactionSigner:
    return SolanaTransactionSigner()


def raise_live_http_error(
    error: LiveTradingError,
) -> None:
    raise HTTPException(
        status_code=error.status_code,
        detail={
            "code": error.code,
            "message": error.message,
            "payload": error.payload,
        },
    ) from error


def resolve_generation_filter(
    db: Session,
    *,
    scope: str,
    mode: str | None = None,
) -> int | None:
    if scope == "ALL":
        return None

    policy = get_or_create_live_policy(
        db
    )

    target_mode = (
        str(mode or policy.mode)
        .strip()
        .upper()
    )

    if target_mode == "DRY_RUN":
        return max(
            1,
            int(
                policy.dry_run_generation
                or 1
            ),
        )

    if target_mode == "LIVE":
        return 1

    return None


@router.get(
    "/status",
    response_model=(
        LiveTradingStatusResponse
    ),
)
def read_live_status(
    db: Session = Depends(get_db),
    rpc_client: SolanaRpcClient = Depends(
        get_solana_rpc_client
    ),
):
    payload = get_live_trading_status(
        db,
        rpc_client=rpc_client,
    )

    payload["worker"] = (
        get_live_worker_status(
            db
        )
    )

    return payload


@router.get(
    "/worker",
    response_model=(
        LiveTradingWorkerStatusResponse
    ),
)
def read_live_worker(
    db: Session = Depends(get_db),
):
    return get_live_worker_status(
        db
    )


@router.get(
    "/policy",
    response_model=(
        LiveTradingPolicyResponse
    ),
)
def read_live_policy(
    db: Session = Depends(get_db),
):
    return get_or_create_live_policy(
        db
    )


@router.patch(
    "/policy",
    response_model=(
        LiveTradingPolicyResponse
    ),
)
def patch_live_policy(
    payload: (
        LiveTradingPolicyUpdateRequest
    ),
    db: Session = Depends(get_db),
):
    try:
        policy = (
            get_or_create_live_policy(
                db
            )
        )

        return update_live_policy(
            db,
            policy,
            payload.model_dump(
                exclude_unset=True
            ),
        )

    except LiveTradingError as error:
        raise_live_http_error(
            error
        )


@router.post(
    "/dry-run/reset",
    response_model=(
        LiveTradingDryRunResetResponse
    ),
)
def reset_dry_run(
    payload: (
        LiveTradingDryRunResetRequest
    ),
    db: Session = Depends(get_db),
):
    try:
        return reset_dry_run_generation(
            db,
            source_wallets=(
                payload.source_wallets
            ),
            start_stream=(
                payload.start_stream
            ),
            buy_enabled=(
                payload.buy_enabled
            ),
            sell_enabled=(
                payload.sell_enabled
            ),
        )

    except LiveTradingError as error:
        raise_live_http_error(
            error
        )


@router.post(
    "/kill-switch",
    response_model=(
        LiveTradingPolicyResponse
    ),
)
def activate_kill_switch(
    db: Session = Depends(get_db),
):
    policy = (
        get_or_create_live_policy(
            db
        )
    )

    return engage_kill_switch(
        db,
        policy,
        reason=(
            "Kill switch attivato "
            "manualmente tramite API."
        ),
    )


@router.post(
    "/kill-switch/release",
    response_model=(
        LiveTradingPolicyResponse
    ),
)
def deactivate_kill_switch(
    payload: KillSwitchReleaseRequest,
    db: Session = Depends(get_db),
):
    policy = (
        get_or_create_live_policy(
            db
        )
    )

    return release_kill_switch(
        db,
        policy,
    )


@router.post(
    "/execute/trades/{trade_id}",
    response_model=(
        LiveCopyOrderResponse
    ),
    status_code=(
        status.HTTP_200_OK
    ),
)
def execute_trade_manually(
    trade_id: int,
    db: Session = Depends(get_db),
    jupiter_client: JupiterSwapClient = Depends(
        get_jupiter_client
    ),
    rpc_client: SolanaRpcClient = Depends(
        get_solana_rpc_client
    ),
    signer: SolanaTransactionSigner = Depends(
        get_transaction_signer
    ),
):
    trade = (
        db.query(Trade)
        .filter(
            Trade.id == trade_id
        )
        .first()
    )

    if trade is None:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail={
                "code":
                    "SOURCE_TRADE_NOT_FOUND",
                "message":
                    "Trade sorgente non trovato.",
            },
        )

    try:
        order = execute_source_trade(
            db,
            trade=trade,
            origin="MANUAL",
            jupiter_client=(
                jupiter_client
            ),
            rpc_client=rpc_client,
            signer=signer,
        )

    except LiveTradingError as error:
        raise_live_http_error(
            error
        )

    if order is None:
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
            ),
            detail={
                "code":
                    "LIVE_EXECUTION_SKIPPED",
                "message":
                    "Esecuzione non avviata.",
            },
        )

    return order


@router.post(
    "/positions/{position_id}/close-dry-run",
    response_model=(
        LiveCopyOrderResponse
    ),
    status_code=(
        status.HTTP_200_OK
    ),
)
def close_position_dry_run(
    position_id: int,
    payload: (
        LiveTradingDryRunCloseRequest
    ),
    db: Session = Depends(get_db),
    jupiter_client: JupiterSwapClient = Depends(
        get_jupiter_client
    ),
):
    try:
        return close_dry_run_position(
            db,
            position_id=position_id,
            jupiter_client=(
                jupiter_client
            ),
        )

    except LiveTradingError as error:
        raise_live_http_error(
            error
        )


@router.get(
    "/orders",
    response_model=(
        LiveOrderListResponse
    ),
)
def read_live_orders(
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),
    order_status: Literal[
        "RECEIVED",
        "REJECTED",
        "DRY_RUN",
        "QUOTED",
        "SUBMITTED",
        "FILLED",
        "FAILED",
    ]
    | None = Query(
        default=None,
        alias="status",
    ),
    mode: Literal[
        "DRY_RUN",
        "LIVE",
    ]
    | None = None,
    scope: Literal[
        "ACTIVE",
        "ALL",
    ] = "ACTIVE",
    db: Session = Depends(get_db),
):
    generation = (
        resolve_generation_filter(
            db,
            scope=scope,
            mode=mode,
        )
    )

    orders = list_live_orders(
        db,
        limit=limit,
        status=order_status,
        mode=mode,
        generation=generation,
    )

    return {
        "count": len(orders),
        "orders": orders,
    }


@router.get(
    "/positions",
    response_model=(
        LivePositionListResponse
    ),
)
def read_live_positions(
    position_status: Literal[
        "OPEN",
        "CLOSED",
    ]
    | None = Query(
        default=None,
        alias="status",
    ),
    mode: Literal[
        "DRY_RUN",
        "LIVE",
    ]
    | None = None,
    scope: Literal[
        "ACTIVE",
        "ALL",
    ] = "ACTIVE",
    db: Session = Depends(get_db),
):
    generation = (
        resolve_generation_filter(
            db,
            scope=scope,
            mode=mode,
        )
    )

    positions = list_live_positions(
        db,
        status=position_status,
        mode=mode,
        generation=generation,
    )

    return {
        "count": len(positions),
        "positions": positions,
    }


@router.get(
    "/events",
    response_model=(
        LiveEventListResponse
    ),
)
def read_live_events(
    limit: int = Query(
        default=200,
        ge=1,
        le=1000,
    ),
    scope: Literal[
        "ACTIVE",
        "ALL",
    ] = "ACTIVE",
    db: Session = Depends(get_db),
):
    generation = (
        resolve_generation_filter(
            db,
            scope=scope,
        )
    )

    events = list_live_events(
        db,
        limit=limit,
        generation=generation,
    )

    return {
        "count": len(events),
        "events": events,
    } 