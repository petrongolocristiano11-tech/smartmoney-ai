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
from backend.app.database.session import (
    get_db,
)
from backend.app.schemas.paper_trading import (
    PaperAccountCreateRequest,
    PaperAccountDetailResponse,
    PaperAccountListItem,
    PaperAccountListResponse,
    PaperAccountResetRequest,
    PaperAccountUpdateRequest,
    PaperBuyRequest,
    PaperExecutionResponse,
    PaperPriceRefreshResponse,
    PaperPriceResponse,
    PaperSellRequest,
)
from backend.app.services.paper_trading_account_service import (
    list_paper_accounts,
    reset_paper_account,
    update_paper_account,
)
from backend.app.services.paper_trading_engine import (
    PaperTradingError,
    create_paper_account,
    get_paper_account,
    get_paper_account_summary,
    list_paper_orders,
    list_paper_positions,
)
from backend.app.services.paper_trading_pricing_service import (
    buy_paper_token_with_oracle,
    get_paper_token_price,
    refresh_paper_account_prices,
    sell_paper_token_with_oracle,
)
from backend.app.services.price_oracle import (
    JupiterPriceOracle,
    PriceOracleError,
    get_price_oracle,
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


ORACLE_SERVICE_CODES = {
    "ORACLE_NOT_CONFIGURED",
    "ORACLE_TIMEOUT",
    "ORACLE_UNAVAILABLE",
    "ORACLE_AUTHENTICATION_FAILED",
    "ORACLE_RATE_LIMITED",
    "SOL_PRICE_NOT_AVAILABLE",
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
            status
            .HTTP_422_UNPROCESSABLE_ENTITY
        )

    raise HTTPException(
        status_code=status_code,
        detail={
            "code": exception.code,
            "message": exception.message,
        },
    ) from exception


def raise_oracle_http_error(
    exception: PriceOracleError,
) -> None:
    if (
        exception.code
        in ORACLE_SERVICE_CODES
    ):
        status_code = (
            status
            .HTTP_503_SERVICE_UNAVAILABLE
        )

    else:
        status_code = (
            status
            .HTTP_422_UNPROCESSABLE_ENTITY
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

    except (
        PaperTradingError
    ) as exception:
        raise_paper_http_error(
            exception
        )

    except (
        PriceOracleError
    ) as exception:
        raise_oracle_http_error(
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
    "/prices/{token_mint}",
    response_model=PaperPriceResponse,
)
def get_token_price(
    token_mint: str,
    force_refresh: bool = Query(
        default=False
    ),
    oracle: JupiterPriceOracle = (
        Depends(get_price_oracle)
    ),
):
    return paper_operation(
        get_paper_token_price,
        oracle=oracle,
        token_mint=token_mint,
        force_refresh=force_refresh,
    )


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
    "/accounts/{account_id}/refresh-prices",
    response_model=(
        PaperPriceRefreshResponse
    ),
)
def refresh_prices(
    account_id: int,
    force_refresh: bool = Query(
        default=False
    ),
    db: Session = Depends(get_db),
    oracle: JupiterPriceOracle = (
        Depends(get_price_oracle)
    ),
):
    return paper_operation(
        refresh_paper_account_prices,
        db=db,
        oracle=oracle,
        account_id=account_id,
        force_refresh=force_refresh,
    )


@router.post(
    "/accounts/{account_id}/buy",
    response_model=(
        PaperExecutionResponse
    ),
)
def buy_token(
    account_id: int,
    payload: PaperBuyRequest,
    db: Session = Depends(get_db),
    oracle: JupiterPriceOracle = (
        Depends(get_price_oracle)
    ),
):
    return paper_operation(
        buy_paper_token_with_oracle,
        db=db,
        oracle=oracle,
        account_id=account_id,
        **payload.model_dump(),
    )


@router.post(
    "/accounts/{account_id}/sell",
    response_model=(
        PaperExecutionResponse
    ),
)
def sell_token(
    account_id: int,
    payload: PaperSellRequest,
    db: Session = Depends(get_db),
    oracle: JupiterPriceOracle = (
        Depends(get_price_oracle)
    ),
):
    return paper_operation(
        sell_paper_token_with_oracle,
        db=db,
        oracle=oracle,
        account_id=account_id,
        **payload.model_dump(),
    ) 