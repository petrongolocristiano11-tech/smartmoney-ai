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
    LiveEventListResponse,
    LiveOrderListResponse,
    LivePositionListResponse,
    LiveTradingPolicyResponse,
    LiveTradingPolicyUpdateRequest,
    LiveTradingStatusResponse,
)
from backend.app.services.jupiter_swap_client import (
    JupiterSwapClient,
)
from backend.app.services.live_copy_trading_engine import (
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
    return get_live_trading_status(
        db,
        rpc_client=rpc_client,
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
    db: Session = Depends(get_db),
):
    orders = list_live_orders(
        db,
        limit=limit,
        status=order_status,
        mode=mode,
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
    db: Session = Depends(get_db),
):
    positions = list_live_positions(
        db,
        status=position_status,
        mode=mode,
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
    db: Session = Depends(get_db),
):
    events = list_live_events(
        db,
        limit=limit,
    )

    return {
        "count": len(events),
        "events": events,
    } 