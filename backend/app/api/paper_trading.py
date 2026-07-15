from collections.abc import Callable
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy.orm import Session

from backend.app.core.paper_trading_security import (
    require_paper_trading_key,
)
from backend.app.database.session import get_db
from backend.app.schemas.paper_trading import (
    PaperAccountCreateRequest,
    PaperAccountDetailResponse,
    PaperAccountListItem,
    PaperAccountListResponse,
    PaperAccountResetRequest,
    PaperAccountUpdateRequest,
    PaperBuyRequest,
    PaperExecutionResponse,
    PaperMarkRequest,
    PaperPositionResponse,
    PaperSellRequest,
)
from backend.app.services.paper_trading_account_service import (
    list_paper_accounts,
    reset_paper_account,
    update_paper_account,
)
from backend.app.services.paper_trading_engine import (
    PaperTradingError,
    buy_paper_token,
    create_paper_account,
    get_paper_account,
    get_paper_account_summary,
    list_paper_orders,
    list_paper_positions,
    mark_paper_position,
    sell_paper_token,
)


router = APIRouter(
    prefix="/paper-trading",
    tags=["Paper Trading"],
    dependencies=[
        Depends(
            require_paper_trading_key
        )
    ],
)


NOT_FOUND_CODES = {
    "ACCOUNT_NOT_FOUND",
    "POSITION_NOT_FOUND",
}

CONFLICT_CODES = {
    "ACCOUNT_NAME_EXISTS",
    "ACCOUNT_NOT_ACTIVE",
    "MAX_POSITION_SIZE",
    "INSUFFICIENT_CASH",
    "DAILY_LOSS_LIMIT",
    "MAX_OPEN_POSITIONS",
    "INSUFFICIENT_QUANTITY",
    "EMPTY_POSITION",
    "RESET_CONFIRMATION_FAILED",
    "POSITION_LIMIT_BELOW_CURRENT_EXPOSURE",
    "OPEN_POSITION_LIMIT_BELOW_CURRENT_COUNT",
}


def raise_paper_http_error(
    exception: PaperTradingError,
) -> None:
    if exception.code in NOT_FOUND_CODES:
        status_code = (
            status.HTTP_404_NOT_FOUND
        )
    elif exception.code in CONFLICT_CODES:
        status_code = (
            status.HTTP_409_CONFLICT
        )
    else:
        status_code = (
            status.HTTP_422_UNPROCESSABLE_ENTITY
        )

    raise HTTPException(
        status_code=status_code,
        detail={
            "code": exception.code,
            "message": exception.message,
        },
    ) from exception


def paper_operation(
    operation: Callable[..., Any],
    *args,
    **kwargs,
):
    try:
        return operation(
            *args,
            **kwargs,
        )
    except PaperTradingError as exception:
        raise_paper_http_error(
            exception
        )


def build_account_detail(
    db: Session,
    account_id: int,
    orders_limit: int = 100,
) -> dict[str, Any]:
    account = paper_operation(
        get_paper_account,
        db,
        account_id,
    )

    positions = paper_operation(
        list_paper_positions,
        db,
        account_id,
    )

    orders = paper_operation(
        list_paper_orders,
        db,
        account_id,
        orders_limit,
    )

    summary = paper_operation(
        get_paper_account_summary,
        db,
        account_id,
    )

    return {
        "account": account,
        "summary": summary,
        "positions": positions,
        "orders": orders,
    }


@router.get(
    "/accounts",
    response_model=(
        PaperAccountListResponse
    ),
)
def get_accounts(
    db: Session = Depends(get_db),
):
    accounts = list_paper_accounts(db)

    rows = [
        PaperAccountListItem(
            account=account,
            summary=(
                get_paper_account_summary(
                    db,
                    account.id,
                )
            ),
        )
        for account in accounts
    ]

    return {
        "count": len(rows),
        "accounts": rows,
    }


@router.post(
    "/accounts",
    response_model=(
        PaperAccountDetailResponse
    ),
    status_code=(
        status.HTTP_201_CREATED
    ),
)
def create_account(
    payload: PaperAccountCreateRequest,
    db: Session = Depends(get_db),
):
    account = paper_operation(
        create_paper_account,
        db=db,
        **payload.model_dump(),
    )

    return build_account_detail(
        db,
        account.id,
    )


@router.get(
    "/accounts/{account_id}",
    response_model=(
        PaperAccountDetailResponse
    ),
)
def get_account_detail(
    account_id: int,
    orders_limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),
    db: Session = Depends(get_db),
):
    return build_account_detail(
        db,
        account_id,
        orders_limit,
    )


@router.patch(
    "/accounts/{account_id}",
    response_model=(
        PaperAccountDetailResponse
    ),
)
def update_account(
    account_id: int,
    payload: PaperAccountUpdateRequest,
    db: Session = Depends(get_db),
):
    updates = payload.model_dump(
        exclude_unset=True
    )

    paper_operation(
        update_paper_account,
        db=db,
        account_id=account_id,
        **updates,
    )

    return build_account_detail(
        db,
        account_id,
    )


@router.post(
    "/accounts/{account_id}/reset",
    response_model=(
        PaperAccountDetailResponse
    ),
)
def reset_account(
    account_id: int,
    payload: PaperAccountResetRequest,
    db: Session = Depends(get_db),
):
    paper_operation(
        reset_paper_account,
        db=db,
        account_id=account_id,
        confirmation_name=(
            payload.confirmation_name
        ),
    )

    return build_account_detail(
        db,
        account_id,
    )


@router.post(
    "/accounts/{account_id}/buy",
    response_model=PaperExecutionResponse,
)
def buy_token(
    account_id: int,
    payload: PaperBuyRequest,
    db: Session = Depends(get_db),
):
    return paper_operation(
        buy_paper_token,
        db=db,
        account_id=account_id,
        **payload.model_dump(),
    )


@router.post(
    "/accounts/{account_id}/sell",
    response_model=PaperExecutionResponse,
)
def sell_token(
    account_id: int,
    payload: PaperSellRequest,
    db: Session = Depends(get_db),
):
    return paper_operation(
        sell_paper_token,
        db=db,
        account_id=account_id,
        **payload.model_dump(),
    )


@router.post(
    "/accounts/{account_id}/mark",
    response_model=PaperPositionResponse,
)
def mark_position(
    account_id: int,
    payload: PaperMarkRequest,
    db: Session = Depends(get_db),
):
    return paper_operation(
        mark_paper_position,
        db=db,
        account_id=account_id,
        token_mint=payload.token_mint,
        market_price_sol=(
            payload.market_price_sol
        ),
    ) 