from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.paper_account import (
    PaperAccount,
)
from backend.app.models.paper_order import (
    PaperOrder,
)
from backend.app.models.paper_position import (
    PaperPosition,
)
from backend.app.services.paper_trading_engine import (
    PaperTradingError,
    get_paper_account,
)


VALID_ACCOUNT_STATUSES = {
    "ACTIVE",
    "PAUSED",
    "STOPPED",
}


def list_paper_accounts(
    db: Session,
) -> list[PaperAccount]:
    return (
        db.query(PaperAccount)
        .order_by(
            PaperAccount.created_at.desc(),
            PaperAccount.id.desc(),
        )
        .all()
    )


def _positive_float(
    value: Any,
    field_name: str,
) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exception:
        raise PaperTradingError(
            f"{field_name} deve essere "
            "un numero valido.",
            code="INVALID_ACCOUNT_SETTING",
        ) from exception

    if normalized <= 0:
        raise PaperTradingError(
            f"{field_name} deve essere "
            "maggiore di zero.",
            code="INVALID_ACCOUNT_SETTING",
        )

    return normalized


def _positive_integer(
    value: Any,
    field_name: str,
) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exception:
        raise PaperTradingError(
            f"{field_name} deve essere "
            "un numero intero valido.",
            code="INVALID_ACCOUNT_SETTING",
        ) from exception

    if normalized <= 0:
        raise PaperTradingError(
            f"{field_name} deve essere "
            "maggiore di zero.",
            code="INVALID_ACCOUNT_SETTING",
        )

    return normalized


def update_paper_account(
    db: Session,
    account_id: int,
    name: str | None = None,
    status: str | None = None,
    max_position_size_sol: (
        float | None
    ) = None,
    max_open_positions: int | None = None,
    daily_loss_limit_sol: (
        float | None
    ) = None,
) -> PaperAccount:
    account = get_paper_account(
        db,
        account_id,
        lock=True,
    )

    open_positions = (
        db.query(PaperPosition)
        .filter(
            PaperPosition.account_id
            == account.id,
            PaperPosition.status == "OPEN",
        )
        .all()
    )

    if name is not None:
        normalized_name = str(
            name
        ).strip()

        if not normalized_name:
            raise PaperTradingError(
                "Il nome del conto non "
                "può essere vuoto.",
                code="INVALID_ACCOUNT_NAME",
            )

        if len(normalized_name) > 80:
            raise PaperTradingError(
                "Il nome del conto supera "
                "80 caratteri.",
                code="INVALID_ACCOUNT_NAME",
            )

        account.name = normalized_name

    if status is not None:
        normalized_status = str(
            status
        ).strip().upper()

        if (
            normalized_status
            not in VALID_ACCOUNT_STATUSES
        ):
            raise PaperTradingError(
                "Stato del conto non valido.",
                code="INVALID_ACCOUNT_STATUS",
            )

        account.status = normalized_status

    if max_position_size_sol is not None:
        normalized_position_limit = (
            _positive_float(
                max_position_size_sol,
                "max_position_size_sol",
            )
        )

        largest_current_position = max(
            (
                float(
                    position.cost_basis_sol
                    or 0.0
                )
                for position in open_positions
            ),
            default=0.0,
        )

        if (
            normalized_position_limit
            < largest_current_position
        ):
            raise PaperTradingError(
                "Il limite per posizione "
                "non può essere inferiore "
                "al costo di una posizione "
                "già aperta.",
                code=(
                    "POSITION_LIMIT_BELOW_"
                    "CURRENT_EXPOSURE"
                ),
            )

        account.max_position_size_sol = (
            normalized_position_limit
        )

    if max_open_positions is not None:
        normalized_open_limit = (
            _positive_integer(
                max_open_positions,
                "max_open_positions",
            )
        )

        if (
            normalized_open_limit
            < len(open_positions)
        ):
            raise PaperTradingError(
                "Il limite di posizioni "
                "non può essere inferiore "
                "al numero di posizioni "
                "attualmente aperte.",
                code=(
                    "OPEN_POSITION_LIMIT_"
                    "BELOW_CURRENT_COUNT"
                ),
            )

        account.max_open_positions = (
            normalized_open_limit
        )

    if daily_loss_limit_sol is not None:
        account.daily_loss_limit_sol = (
            _positive_float(
                daily_loss_limit_sol,
                "daily_loss_limit_sol",
            )
        )

    try:
        db.commit()
    except IntegrityError as exception:
        db.rollback()

        raise PaperTradingError(
            "Esiste già un conto con "
            "questo nome.",
            code="ACCOUNT_NAME_EXISTS",
        ) from exception

    db.refresh(account)

    return account


def reset_paper_account(
    db: Session,
    account_id: int,
    confirmation_name: str,
) -> PaperAccount:
    account = get_paper_account(
        db,
        account_id,
        lock=True,
    )

    normalized_confirmation = str(
        confirmation_name or ""
    ).strip()

    if normalized_confirmation != account.name:
        raise PaperTradingError(
            "Il nome di conferma non "
            "corrisponde al conto.",
            code="RESET_CONFIRMATION_FAILED",
        )

    (
        db.query(PaperOrder)
        .filter(
            PaperOrder.account_id
            == account.id
        )
        .delete(
            synchronize_session=False
        )
    )

    (
        db.query(PaperPosition)
        .filter(
            PaperPosition.account_id
            == account.id
        )
        .delete(
            synchronize_session=False
        )
    )

    account.status = "ACTIVE"
    account.cash_balance_sol = float(
        account.starting_balance_sol
    )
    account.realized_pnl_sol = 0.0

    db.commit()
    db.refresh(account)

    return account 