from math import ceil
from secrets import compare_digest
from threading import Lock
from time import monotonic
from typing import Annotated

from fastapi import (
    Header,
    HTTPException,
    status,
)

from backend.app.core.config import (
    settings,
)


_public_discovery_lock = Lock()
_last_public_discovery_at = 0.0


def require_automation_key(
    x_automation_key: Annotated[
        str | None,
        Header(
            alias="X-Automation-Key"
        ),
    ] = None,
) -> None:
    expected_key = (
        settings.AUTOMATION_API_KEY
    )

    if not expected_key:
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=(
                "Automazione non configurata."
            ),
        )

    supplied_key = (
        x_automation_key or ""
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
            detail=(
                "Credenziali di automazione "
                "non valide."
            ),
        )


def enforce_public_discovery_cooldown(
) -> None:
    global _last_public_discovery_at

    now = monotonic()

    cooldown_seconds = (
        settings
        .PUBLIC_DISCOVERY_COOLDOWN_SECONDS
    )

    with _public_discovery_lock:
        elapsed_seconds = (
            now
            - _last_public_discovery_at
        )

        remaining_seconds = (
            cooldown_seconds
            - elapsed_seconds
        )

        if (
            _last_public_discovery_at > 0
            and remaining_seconds > 0
        ):
            retry_after = max(
                ceil(remaining_seconds),
                1,
            )

            raise HTTPException(
                status_code=(
                    status
                    .HTTP_429_TOO_MANY_REQUESTS
                ),
                detail=(
                    "Una Discovery manuale è "
                    "già stata avviata di "
                    "recente. Riprova tra "
                    f"{retry_after} secondi."
                ),
                headers={
                    "Retry-After": str(
                        retry_after
                    ),
                },
            )

        _last_public_discovery_at = now 