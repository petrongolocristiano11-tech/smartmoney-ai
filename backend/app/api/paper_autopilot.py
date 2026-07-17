from collections.abc import Callable
from typing import Any
from backend.app.schemas.paper_autopilot_analytics import (
    PaperAutopilotAnalyticsResponse,
)
from backend.app.services.paper_autopilot_analytics import (
    build_paper_autopilot_analytics,
)
from fastapi import (
    APIRouter, 
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy.orm import Session

from backend.app.core.discovery_security import (
    require_automation_key,
)
from backend.app.core.paper_trading_security import (
    require_paper_trading_key,
)
from backend.app.database.session import (
    get_db,
)
from backend.app.models.paper_autopilot import (
    PaperAutopilotPolicy,
)
from backend.app.schemas.paper_autopilot import (
    PaperAutopilotAutomationResponse,
    PaperAutopilotDashboardResponse,
    PaperAutopilotExecutionResponse,
    PaperAutopilotPolicyUpdateRequest,
)
from backend.app.services.paper_autopilot_engine import (
    PaperAutopilotError,
    get_or_create_autopilot_policy,
    list_autopilot_decisions,
    list_autopilot_runs,
    list_managed_positions,
    run_paper_autopilot,
)
from backend.app.services.paper_autopilot_policy_service import (
    update_autopilot_policy,
)
from backend.app.services.paper_trading_engine import (
    PaperTradingError,
    get_paper_account,
    get_paper_account_summary,
)
from backend.app.services.price_oracle import (
    JupiterPriceOracle,
    PriceOracleError,
    get_price_oracle,
)
from backend.app.services.signals_engine import (
    get_token_signals,
)


router = APIRouter(
    prefix="/paper-autopilot",
    tags=["Paper Autopilot"],
)

def get_autopilot_signal_provider(
) -> Callable[
    ...,
    dict[str, Any],
]:
    return get_token_signals 

def get_autopilot_signal_provider(
) -> Callable[
    ...,
    dict[str, Any],
]:
    return get_token_signals


def raise_autopilot_http_error(
    exception: Exception,
) -> None:
    code = getattr(
        exception,
        "code",
        "PAPER_AUTOPILOT_ERROR",
    )

    message = getattr(
        exception,
        "message",
        str(exception),
    )

    if code in {
        "ACCOUNT_NOT_FOUND",
        "POSITION_NOT_FOUND",
    }:
        status_code = (
            status.HTTP_404_NOT_FOUND
        )

    elif code in {
        "AUTOPILOT_RUN_ALREADY_ACTIVE",
        "ACCOUNT_NOT_ACTIVE_FOR_AUTOPILOT",
        "ACCOUNT_NOT_ACTIVE",
        "MAX_POSITION_SIZE",
        "INSUFFICIENT_CASH",
        "DAILY_LOSS_LIMIT",
        "MAX_OPEN_POSITIONS",
    }:
        status_code = (
            status.HTTP_409_CONFLICT
        )

    elif code in {
        "ORACLE_NOT_CONFIGURED",
        "ORACLE_TIMEOUT",
        "ORACLE_UNAVAILABLE",
        "ORACLE_AUTHENTICATION_FAILED",
        "ORACLE_RATE_LIMITED",
        "SOL_PRICE_NOT_AVAILABLE",
    }:
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
            "code": code,
            "message": message,
        },
    ) from exception


def autopilot_operation(
    operation,
    *args,
    **kwargs,
):
    try:
        return operation(
            *args,
            **kwargs,
        )

    except (
        PaperAutopilotError,
        PaperTradingError,
        PriceOracleError,
    ) as exception:
        raise_autopilot_http_error(
            exception
        )


def build_autopilot_dashboard(
    db: Session,
    account_id: int,
    runs_limit: int = 30,
    decisions_limit: int = 100,
) -> dict[str, Any]:
    account = autopilot_operation(
        get_paper_account,
        db,
        account_id,
    )

    policy = autopilot_operation(
        get_or_create_autopilot_policy,
        db,
        account_id,
    )

    return {
        "account": account,
        "summary": (
            get_paper_account_summary(
                db,
                account_id,
            )
        ),
        "policy": policy,
        "runs": list_autopilot_runs(
            db,
            account_id,
            limit=runs_limit,
        ),
        "decisions": (
            list_autopilot_decisions(
                db,
                account_id,
                limit=decisions_limit,
            )
        ),
        "managed_positions": (
            list_managed_positions(
                db,
                account_id,
            )
        ),
    }


@router.get(
    "/accounts/{account_id}",
    response_model=(
        PaperAutopilotDashboardResponse
    ),
    dependencies=[
        Depends(
            require_paper_trading_key
        )
    ],
)
def get_autopilot_dashboard(
    account_id: int,
    runs_limit: int = Query(
        default=30,
        ge=1,
        le=500,
    ),
    decisions_limit: int = Query(
        default=100,
        ge=1,
        le=1_000,
    ),
    db: Session = Depends(get_db),
):
    return build_autopilot_dashboard(
        db,
        account_id,
        runs_limit=runs_limit,
        decisions_limit=(
            decisions_limit
        ),
    )


@router.patch(
    "/accounts/{account_id}/policy",
    response_model=(
        PaperAutopilotDashboardResponse
    ),
    dependencies=[
        Depends(
            require_paper_trading_key
        )
    ],
)
def patch_autopilot_policy(
    account_id: int,
    payload: (
        PaperAutopilotPolicyUpdateRequest
    ),
    db: Session = Depends(get_db),
):
    autopilot_operation(
        update_autopilot_policy,
        db=db,
        account_id=account_id,
        updates=payload.model_dump(
            exclude_unset=True
        ),
    )

    return build_autopilot_dashboard(
        db,
        account_id,
    )


@router.post(
    "/accounts/{account_id}/run",
    response_model=(
        PaperAutopilotExecutionResponse
    ),
    dependencies=[
        Depends(
            require_paper_trading_key
        )
    ],
)
def run_autopilot_manually(
    account_id: int,
    db: Session = Depends(get_db),
    oracle: JupiterPriceOracle = (
        Depends(get_price_oracle)
    ),
    signal_provider: Callable[
        ...,
        dict[str, Any],
    ] = Depends(
        get_autopilot_signal_provider
    ),
):
    return autopilot_operation(
        run_paper_autopilot,
        db=db,
        oracle=oracle,
        account_id=account_id,
        trigger="MANUAL",
        signal_provider=(
            signal_provider
        ),
    )

@router.get(
    "/accounts/{account_id}/analytics",
    response_model=(
        PaperAutopilotAnalyticsResponse
    ),
    dependencies=[
        Depends(
            require_paper_trading_key
        )
    ],
)
def get_autopilot_analytics(
    account_id: int,
    days: int = Query(
        default=30,
        ge=1,
        le=365,
    ),
    db: Session = Depends(get_db),
):
    return autopilot_operation(
        build_paper_autopilot_analytics,
        db,
        account_id,
        days=days,
    )

@router.post(
    "/automation/run",
    response_model=(
        PaperAutopilotAutomationResponse
    ),
    dependencies=[
        Depends(
            require_automation_key
        )
    ],
)
def run_autopilot_automation(
    db: Session = Depends(get_db),
    oracle: JupiterPriceOracle = (
        Depends(get_price_oracle)
    ),
    signal_provider: Callable[
        ...,
        dict[str, Any],
    ] = Depends(
        get_autopilot_signal_provider
    ),
):
    policies = (
        db.query(
            PaperAutopilotPolicy
        )
        .filter(
            PaperAutopilotPolicy
            .status
            .in_(
                [
                    "ENABLED",
                    "PAUSED",
                ]
            )
        )
        .order_by(
            PaperAutopilotPolicy
            .account_id
            .asc()
        )
        .all()
    )

    results: list[
        dict[str, Any]
    ] = []

    successful_runs = 0
    failed_runs = 0

    for policy in policies:
        try:
            result = run_paper_autopilot(
                db=db,
                oracle=oracle,
                account_id=(
                    policy.account_id
                ),
                trigger="AUTOMATION",
                signal_provider=(
                    signal_provider
                ),
            )

            successful_runs += 1

            results.append(
                {
                    "account_id": (
                        policy.account_id
                    ),
                    "success": True,
                    "run": result["run"],
                    "error_code": None,
                    "error_message": None,
                }
            )

        except Exception as exception:
            db.rollback()
            failed_runs += 1

            results.append(
                {
                    "account_id": (
                        policy.account_id
                    ),
                    "success": False,
                    "run": None,
                    "error_code": getattr(
                        exception,
                        "code",
                        type(
                            exception
                        ).__name__,
                    ),
                    "error_message": getattr(
                        exception,
                        "message",
                        str(exception),
                    )[:2_000],
                }
            )

    return {
        "processed_accounts": len(
            policies
        ),
        "successful_runs": (
            successful_runs
        ),
        "failed_runs": (
            failed_runs
        ),
        "results": results,
    } 