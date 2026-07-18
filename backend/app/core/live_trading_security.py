from secrets import compare_digest
from typing import Annotated

from fastapi import (
    Header,
    HTTPException,
    status,
)

from backend.app.core.config import (
    settings,
)


def require_live_trading_key(
    x_live_trading_key: Annotated[
        str | None,
        Header(
            alias="X-Live-Trading-Key"
        ),
    ] = None,
) -> None:
    expected_key = (
        settings.LIVE_TRADING_API_KEY
    )

    if not expected_key:
        raise HTTPException(
            status_code=(
                status
                .HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail={
                "code": (
                    "LIVE_TRADING_NOT_CONFIGURED"
                ),
                "message": (
                    "Live Trading non configurato."
                ),
            },
        )

    supplied_key = str(
        x_live_trading_key or ""
    ).strip()

    if (
        not supplied_key
        or not compare_digest(
            supplied_key,
            expected_key,
        )
    ):
        raise HTTPException(
            status_code=(
                status.HTTP_401_UNAUTHORIZED
            ),
            detail={
                "code": (
                    "INVALID_LIVE_TRADING_KEY"
                ),
                "message": (
                    "Chiave Live Trading non valida."
                ),
            },
        ) 