from datetime import (
    datetime,
    timedelta,
    timezone,
)
from typing import Any

from sqlalchemy import func
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


DEFAULT_SLIPPAGE_PERCENT = 0.50
DEFAULT_FEE_PERCENT = 0.25

MAX_SLIPPAGE_PERCENT = 50.0
MAX_FEE_PERCENT = 20.0

QUANTITY_EPSILON = 1e-12


class PaperTradingError(Exception):
    def __init__(
        self,
        message: str,
        code: str = "PAPER_TRADING_ERROR",
    ):
        super().__init__(message)

        self.message = message
        self.code = code


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_positive_float(
    value: Any,
    field_name: str,
) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exception:
        raise PaperTradingError(
            f"{field_name} deve essere "
            "un numero valido.",
            code="INVALID_NUMBER",
        ) from exception

    if normalized <= 0:
        raise PaperTradingError(
            f"{field_name} deve essere "
            "maggiore di zero.",
            code="INVALID_NUMBER",
        )

    return normalized


def _as_positive_integer(
    value: Any,
    field_name: str,
) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exception:
        raise PaperTradingError(
            f"{field_name} deve essere "
            "un numero intero valido.",
            code="INVALID_INTEGER",
        ) from exception

    if normalized <= 0:
        raise PaperTradingError(
            f"{field_name} deve essere "
            "maggiore di zero.",
            code="INVALID_INTEGER",
        )

    return normalized


def _validate_percentage(
    value: Any,
    field_name: str,
    maximum: float,
) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exception:
        raise PaperTradingError(
            f"{field_name} deve essere "
            "un numero valido.",
            code="INVALID_PERCENTAGE",
        ) from exception

    if normalized < 0 or normalized > maximum:
        raise PaperTradingError(
            f"{field_name} deve essere "
            f"compreso tra 0 e {maximum}.",
            code="INVALID_PERCENTAGE",
        )

    return normalized


def _validate_signal_score(
    value: float | None,
) -> float | None:
    if value is None:
        return None

    normalized = float(value)

    if normalized < 0 or normalized > 100:
        raise PaperTradingError(
            "signal_score deve essere "
            "compreso tra 0 e 100.",
            code="INVALID_SIGNAL_SCORE",
        )

    return normalized


def _normalize_token_mint(
    token_mint: str,
) -> str:
    normalized = str(
        token_mint or ""
    ).strip()

    if not normalized:
        raise PaperTradingError(
            "Il token mint è obbligatorio.",
            code="INVALID_TOKEN",
        )

    if len(normalized) > 64:
        raise PaperTradingError(
            "Il token mint supera "
            "la lunghezza consentita.",
            code="INVALID_TOKEN",
        )

    return normalized


def get_paper_account(
    db: Session,
    account_id: int,
    lock: bool = False,
) -> PaperAccount:
    query = db.query(
        PaperAccount
    ).filter(
        PaperAccount.id == account_id
    )

    if lock:
        query = query.with_for_update()

    account = query.first()

    if account is None:
        raise PaperTradingError(
            "Conto paper trading "
            "non trovato.",
            code="ACCOUNT_NOT_FOUND",
        )

    return account


def create_paper_account(
    db: Session,
    name: str,
    starting_balance_sol: float = 10.0,
    max_position_size_sol: float = 0.5,
    max_open_positions: int = 3,
    daily_loss_limit_sol: float = 1.0,
) -> PaperAccount:
    normalized_name = str(
        name or ""
    ).strip()

    if not normalized_name:
        raise PaperTradingError(
            "Il nome del conto è "
            "obbligatorio.",
            code="INVALID_ACCOUNT_NAME",
        )

    if len(normalized_name) > 80:
        raise PaperTradingError(
            "Il nome del conto supera "
            "80 caratteri.",
            code="INVALID_ACCOUNT_NAME",
        )

    starting_balance = (
        _as_positive_float(
            starting_balance_sol,
            "starting_balance_sol",
        )
    )

    max_position_size = (
        _as_positive_float(
            max_position_size_sol,
            "max_position_size_sol",
        )
    )

    max_positions = (
        _as_positive_integer(
            max_open_positions,
            "max_open_positions",
        )
    )

    daily_loss_limit = (
        _as_positive_float(
            daily_loss_limit_sol,
            "daily_loss_limit_sol",
        )
    )

    existing_account = (
        db.query(PaperAccount)
        .filter(
            PaperAccount.name
            == normalized_name
        )
        .first()
    )

    if existing_account is not None:
        raise PaperTradingError(
            "Esiste già un conto con "
            "questo nome.",
            code="ACCOUNT_NAME_EXISTS",
        )

    account = PaperAccount(
        name=normalized_name,
        status="ACTIVE",
        starting_balance_sol=(
            starting_balance
        ),
        cash_balance_sol=(
            starting_balance
        ),
        realized_pnl_sol=0.0,
        max_position_size_sol=(
            max_position_size
        ),
        max_open_positions=(
            max_positions
        ),
        daily_loss_limit_sol=(
            daily_loss_limit
        ),
    )

    db.add(account)

    try:
        db.commit()
    except IntegrityError as exception:
        db.rollback()

        raise PaperTradingError(
            "Impossibile creare il conto: "
            "nome già utilizzato.",
            code="ACCOUNT_NAME_EXISTS",
        ) from exception

    db.refresh(account)

    return account


def list_paper_positions(
    db: Session,
    account_id: int,
    status: str | None = None,
) -> list[PaperPosition]:
    get_paper_account(
        db,
        account_id,
    )

    query = (
        db.query(PaperPosition)
        .filter(
            PaperPosition.account_id
            == account_id
        )
    )

    if status:
        normalized_status = (
            str(status).strip().upper()
        )

        if normalized_status not in {
            "OPEN",
            "CLOSED",
        }:
            raise PaperTradingError(
                "Lo stato posizione deve "
                "essere OPEN o CLOSED.",
                code="INVALID_POSITION_STATUS",
            )

        query = query.filter(
            PaperPosition.status
            == normalized_status
        )

    return (
        query.order_by(
            PaperPosition.updated_at.desc()
        )
        .all()
    )


def list_paper_orders(
    db: Session,
    account_id: int,
    limit: int = 100,
) -> list[PaperOrder]:
    get_paper_account(
        db,
        account_id,
    )

    normalized_limit = max(
        1,
        min(int(limit), 500),
    )

    return (
        db.query(PaperOrder)
        .filter(
            PaperOrder.account_id
            == account_id
        )
        .order_by(
            PaperOrder.created_at.desc()
        )
        .limit(normalized_limit)
        .all()
    )


def get_daily_realized_pnl(
    db: Session,
    account_id: int,
    now: datetime | None = None,
) -> float:
    current_time = now or utc_now()

    if current_time.tzinfo is None:
        current_time = (
            current_time.replace(
                tzinfo=timezone.utc
            )
        )
    else:
        current_time = (
            current_time.astimezone(
                timezone.utc
            )
        )

    day_start = datetime(
        current_time.year,
        current_time.month,
        current_time.day,
        tzinfo=timezone.utc,
    )

    day_end = day_start + timedelta(
        days=1
    )

    result = (
        db.query(
            func.coalesce(
                func.sum(
                    PaperOrder
                    .realized_pnl_sol
                ),
                0.0,
            )
        )
        .filter(
            PaperOrder.account_id
            == account_id,
            PaperOrder.side == "SELL",
            PaperOrder.status
            == "FILLED",
            PaperOrder.executed_at
            >= day_start,
            PaperOrder.executed_at
            < day_end,
        )
        .scalar()
    )

    return float(result or 0.0)


def get_paper_account_summary(
    db: Session,
    account_id: int,
) -> dict[str, Any]:
    account = get_paper_account(
        db,
        account_id,
    )

    positions = (
        db.query(PaperPosition)
        .filter(
            PaperPosition.account_id
            == account_id,
            PaperPosition.status
            == "OPEN",
        )
        .all()
    )

    market_value_sol = sum(
        float(
            position.market_value_sol
            or 0.0
        )
        for position in positions
    )

    unrealized_pnl_sol = sum(
        float(
            position.unrealized_pnl_sol
            or 0.0
        )
        for position in positions
    )

    cash_balance_sol = float(
        account.cash_balance_sol or 0.0
    )

    equity_sol = (
        cash_balance_sol
        + market_value_sol
    )

    starting_balance_sol = float(
        account.starting_balance_sol
        or 0.0
    )

    total_return_percent = (
        (
            equity_sol
            - starting_balance_sol
        )
        / starting_balance_sol
        * 100
        if starting_balance_sol > 0
        else 0.0
    )

    daily_realized_pnl_sol = (
        get_daily_realized_pnl(
            db,
            account_id,
        )
    )

    daily_loss_used_sol = max(
        0.0,
        -daily_realized_pnl_sol,
    )

    return {
        "account_id": account.id,
        "name": account.name,
        "status": account.status,
        "starting_balance_sol": round(
            starting_balance_sol,
            12,
        ),
        "cash_balance_sol": round(
            cash_balance_sol,
            12,
        ),
        "market_value_sol": round(
            market_value_sol,
            12,
        ),
        "equity_sol": round(
            equity_sol,
            12,
        ),
        "realized_pnl_sol": round(
            float(
                account.realized_pnl_sol
                or 0.0
            ),
            12,
        ),
        "unrealized_pnl_sol": round(
            unrealized_pnl_sol,
            12,
        ),
        "daily_realized_pnl_sol": round(
            daily_realized_pnl_sol,
            12,
        ),
        "daily_loss_used_sol": round(
            daily_loss_used_sol,
            12,
        ),
        "daily_loss_limit_sol": float(
            account.daily_loss_limit_sol
        ),
        "total_return_percent": round(
            total_return_percent,
            6,
        ),
        "open_positions": len(
            positions
        ),
        "max_open_positions": (
            account.max_open_positions
        ),
        "max_position_size_sol": float(
            account.max_position_size_sol
        ),
    }


def _assert_buy_allowed(
    db: Session,
    account: PaperAccount,
    position: PaperPosition | None,
    required_cash_sol: float,
    projected_cost_basis_sol: float,
) -> None:
    if account.status != "ACTIVE":
        raise PaperTradingError(
            "Il conto non è attivo.",
            code="ACCOUNT_NOT_ACTIVE",
        )

    if (
        projected_cost_basis_sol
        > float(
            account.max_position_size_sol
        )
        + QUANTITY_EPSILON
    ):
        raise PaperTradingError(
            "L'operazione supererebbe "
            "la dimensione massima "
            "consentita per posizione.",
            code="MAX_POSITION_SIZE",
        )

    if (
        required_cash_sol
        > float(
            account.cash_balance_sol
        )
        + QUANTITY_EPSILON
    ):
        raise PaperTradingError(
            "Saldo virtuale "
            "insufficiente.",
            code="INSUFFICIENT_CASH",
        )

    daily_realized_pnl = (
        get_daily_realized_pnl(
            db,
            account.id,
        )
    )

    daily_loss_used = max(
        0.0,
        -daily_realized_pnl,
    )

    if (
        daily_loss_used
        >= float(
            account.daily_loss_limit_sol
        )
    ):
        raise PaperTradingError(
            "Limite di perdita "
            "giornaliera raggiunto.",
            code="DAILY_LOSS_LIMIT",
        )

    opens_new_position = (
        position is None
        or position.status != "OPEN"
    )

    if opens_new_position:
        open_positions = (
            db.query(PaperPosition)
            .filter(
                PaperPosition.account_id
                == account.id,
                PaperPosition.status
                == "OPEN",
            )
            .count()
        )

        if (
            open_positions
            >= account.max_open_positions
        ):
            raise PaperTradingError(
                "Numero massimo di "
                "posizioni aperte raggiunto.",
                code="MAX_OPEN_POSITIONS",
            )


def buy_paper_token(
    db: Session,
    account_id: int,
    token_mint: str,
    value_sol: float,
    market_price_sol: float,
    slippage_percent: float = (
        DEFAULT_SLIPPAGE_PERCENT
    ),
    fee_percent: float = (
        DEFAULT_FEE_PERCENT
    ),
    signal_score: float | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    token = _normalize_token_mint(
        token_mint
    )

    requested_value = (
        _as_positive_float(
            value_sol,
            "value_sol",
        )
    )

    market_price = (
        _as_positive_float(
            market_price_sol,
            "market_price_sol",
        )
    )

    slippage = _validate_percentage(
        slippage_percent,
        "slippage_percent",
        MAX_SLIPPAGE_PERCENT,
    )

    fee_rate = _validate_percentage(
        fee_percent,
        "fee_percent",
        MAX_FEE_PERCENT,
    )

    normalized_signal_score = (
        _validate_signal_score(
            signal_score
        )
    )

    account = get_paper_account(
        db,
        account_id,
        lock=True,
    )

    position = (
        db.query(PaperPosition)
        .filter(
            PaperPosition.account_id
            == account.id,
            PaperPosition.token_mint
            == token,
        )
        .with_for_update()
        .first()
    )

    execution_price = (
        market_price
        * (
            1
            + slippage / 100
        )
    )

    fee_sol = (
        requested_value
        * fee_rate
        / 100
    )

    required_cash = (
        requested_value
        + fee_sol
    )

    current_cost_basis = (
        float(
            position.cost_basis_sol
            or 0.0
        )
        if position is not None
        and position.status == "OPEN"
        else 0.0
    )

    projected_cost_basis = (
        current_cost_basis
        + required_cash
    )

    _assert_buy_allowed(
        db=db,
        account=account,
        position=position,
        required_cash_sol=(
            required_cash
        ),
        projected_cost_basis_sol=(
            projected_cost_basis
        ),
    )

    quantity = (
        requested_value
        / execution_price
    )

    executed_at = utc_now()

    if position is None:
        position = PaperPosition(
            account_id=account.id,
            token_mint=token,
            status="OPEN",
            quantity=0.0,
            average_entry_price_sol=0.0,
            cost_basis_sol=0.0,
            last_price_sol=market_price,
            market_value_sol=0.0,
            unrealized_pnl_sol=0.0,
            realized_pnl_sol=0.0,
            opened_at=executed_at,
        )

        db.add(position)
        db.flush()

    elif position.status == "CLOSED":
        position.status = "OPEN"
        position.quantity = 0.0
        position.average_entry_price_sol = (
            0.0
        )
        position.cost_basis_sol = 0.0
        position.last_price_sol = (
            market_price
        )
        position.market_value_sol = 0.0
        position.unrealized_pnl_sol = 0.0
        position.opened_at = executed_at
        position.closed_at = None

    new_quantity = (
        float(position.quantity or 0.0)
        + quantity
    )

    new_cost_basis = (
        float(
            position.cost_basis_sol
            or 0.0
        )
        + required_cash
    )

    position.quantity = new_quantity
    position.cost_basis_sol = (
        new_cost_basis
    )
    position.average_entry_price_sol = (
        new_cost_basis
        / new_quantity
    )
    position.last_price_sol = market_price
    position.market_value_sol = (
        new_quantity
        * market_price
    )
    position.unrealized_pnl_sol = (
        position.market_value_sol
        - new_cost_basis
    )

    account.cash_balance_sol = max(
        0.0,
        float(
            account.cash_balance_sol
        )
        - required_cash,
    )

    order = PaperOrder(
        account_id=account.id,
        position_id=position.id,
        token_mint=token,
        side="BUY",
        status="FILLED",
        requested_value_sol=(
            requested_value
        ),
        quantity=quantity,
        execution_price_sol=(
            execution_price
        ),
        gross_value_sol=(
            requested_value
        ),
        fee_sol=fee_sol,
        slippage_percent=slippage,
        realized_pnl_sol=0.0,
        signal_score=(
            normalized_signal_score
        ),
        reason=(
            str(reason).strip()
            if reason
            else None
        ),
        executed_at=executed_at,
    )

    db.add(order)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(account)
    db.refresh(position)
    db.refresh(order)

    return {
        "account": account,
        "position": position,
        "order": order,
        "summary": (
            get_paper_account_summary(
                db,
                account.id,
            )
        ),
    }


def mark_paper_position(
    db: Session,
    account_id: int,
    token_mint: str,
    market_price_sol: float,
) -> PaperPosition:
    token = _normalize_token_mint(
        token_mint
    )

    market_price = (
        _as_positive_float(
            market_price_sol,
            "market_price_sol",
        )
    )

    get_paper_account(
        db,
        account_id,
    )

    position = (
        db.query(PaperPosition)
        .filter(
            PaperPosition.account_id
            == account_id,
            PaperPosition.token_mint
            == token,
            PaperPosition.status
            == "OPEN",
        )
        .with_for_update()
        .first()
    )

    if position is None:
        raise PaperTradingError(
            "Posizione aperta "
            "non trovata.",
            code="POSITION_NOT_FOUND",
        )

    position.last_price_sol = market_price
    position.market_value_sol = (
        float(position.quantity)
        * market_price
    )
    position.unrealized_pnl_sol = (
        position.market_value_sol
        - float(
            position.cost_basis_sol
        )
    )

    db.commit()
    db.refresh(position)

    return position


def sell_paper_token(
    db: Session,
    account_id: int,
    token_mint: str,
    market_price_sol: float,
    quantity: float | None = None,
    slippage_percent: float = (
        DEFAULT_SLIPPAGE_PERCENT
    ),
    fee_percent: float = (
        DEFAULT_FEE_PERCENT
    ),
    signal_score: float | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    token = _normalize_token_mint(
        token_mint
    )

    market_price = (
        _as_positive_float(
            market_price_sol,
            "market_price_sol",
        )
    )

    slippage = _validate_percentage(
        slippage_percent,
        "slippage_percent",
        MAX_SLIPPAGE_PERCENT,
    )

    fee_rate = _validate_percentage(
        fee_percent,
        "fee_percent",
        MAX_FEE_PERCENT,
    )

    normalized_signal_score = (
        _validate_signal_score(
            signal_score
        )
    )

    account = get_paper_account(
        db,
        account_id,
        lock=True,
    )

    position = (
        db.query(PaperPosition)
        .filter(
            PaperPosition.account_id
            == account.id,
            PaperPosition.token_mint
            == token,
            PaperPosition.status
            == "OPEN",
        )
        .with_for_update()
        .first()
    )

    if position is None:
        raise PaperTradingError(
            "Posizione aperta "
            "non trovata.",
            code="POSITION_NOT_FOUND",
        )

    current_quantity = float(
        position.quantity or 0.0
    )

    if current_quantity <= 0:
        raise PaperTradingError(
            "La posizione non contiene "
            "quantità vendibili.",
            code="EMPTY_POSITION",
        )

    if quantity is None:
        sell_quantity = (
            current_quantity
        )
    else:
        sell_quantity = (
            _as_positive_float(
                quantity,
                "quantity",
            )
        )

    if (
        sell_quantity
        > current_quantity
        + QUANTITY_EPSILON
    ):
        raise PaperTradingError(
            "La quantità richiesta supera "
            "quella disponibile.",
            code="INSUFFICIENT_QUANTITY",
        )

    sell_quantity = min(
        sell_quantity,
        current_quantity,
    )

    execution_price = (
        market_price
        * (
            1
            - slippage / 100
        )
    )

    if execution_price <= 0:
        raise PaperTradingError(
            "Lo slippage produce un prezzo "
            "di esecuzione non valido.",
            code="INVALID_EXECUTION_PRICE",
        )

    gross_value = (
        sell_quantity
        * execution_price
    )

    fee_sol = (
        gross_value
        * fee_rate
        / 100
    )

    quantity_ratio = (
        sell_quantity
        / current_quantity
    )

    allocated_cost_basis = (
        float(
            position.cost_basis_sol
            or 0.0
        )
        * quantity_ratio
    )

    net_proceeds = (
        gross_value
        - fee_sol
    )

    realized_pnl = (
        net_proceeds
        - allocated_cost_basis
    )

    remaining_quantity = max(
        0.0,
        current_quantity
        - sell_quantity,
    )

    remaining_cost_basis = max(
        0.0,
        float(
            position.cost_basis_sol
            or 0.0
        )
        - allocated_cost_basis,
    )

    account.cash_balance_sol = (
        float(
            account.cash_balance_sol
            or 0.0
        )
        + net_proceeds
    )

    account.realized_pnl_sol = (
        float(
            account.realized_pnl_sol
            or 0.0
        )
        + realized_pnl
    )

    position.quantity = (
        remaining_quantity
    )
    position.cost_basis_sol = (
        remaining_cost_basis
    )
    position.last_price_sol = (
        market_price
    )
    position.realized_pnl_sol = (
        float(
            position.realized_pnl_sol
            or 0.0
        )
        + realized_pnl
    )

    if (
        remaining_quantity
        <= QUANTITY_EPSILON
    ):
        position.status = "CLOSED"
        position.quantity = 0.0
        position.cost_basis_sol = 0.0
        position.average_entry_price_sol = (
            0.0
        )
        position.market_value_sol = 0.0
        position.unrealized_pnl_sol = 0.0
        position.closed_at = utc_now()
    else:
        position.average_entry_price_sol = (
            remaining_cost_basis
            / remaining_quantity
        )

        position.market_value_sol = (
            remaining_quantity
            * market_price
        )

        position.unrealized_pnl_sol = (
            position.market_value_sol
            - remaining_cost_basis
        )

    order = PaperOrder(
        account_id=account.id,
        position_id=position.id,
        token_mint=token,
        side="SELL",
        status="FILLED",
        requested_value_sol=(
            gross_value
        ),
        quantity=sell_quantity,
        execution_price_sol=(
            execution_price
        ),
        gross_value_sol=gross_value,
        fee_sol=fee_sol,
        slippage_percent=slippage,
        realized_pnl_sol=(
            realized_pnl
        ),
        signal_score=(
            normalized_signal_score
        ),
        reason=(
            str(reason).strip()
            if reason
            else None
        ),
        executed_at=utc_now(),
    )

    db.add(order)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(account)
    db.refresh(position)
    db.refresh(order)

    return {
        "account": account,
        "position": position,
        "order": order,
        "summary": (
            get_paper_account_summary(
                db,
                account.id,
            )
        ),
    } 