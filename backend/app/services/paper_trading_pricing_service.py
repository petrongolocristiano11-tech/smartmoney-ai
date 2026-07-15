from datetime import (
    datetime,
    timezone,
)
from typing import Any

from sqlalchemy.orm import Session

from backend.app.models.paper_position import (
    PaperPosition,
)
from backend.app.services.paper_trading_engine import (
    buy_paper_token,
    get_paper_account,
    get_paper_account_summary,
    sell_paper_token,
)
from backend.app.services.price_oracle import (
    JupiterPriceOracle,
    OraclePrice,
)


def _quote_payload(
    quote: OraclePrice,
) -> dict[str, Any]:
    return quote.as_dict()


def get_paper_token_price(
    oracle: JupiterPriceOracle,
    token_mint: str,
    force_refresh: bool = False,
) -> dict[str, Any]:
    quote = oracle.get_price(
        token_mint,
        force_refresh=force_refresh,
    )

    return _quote_payload(quote)


def buy_paper_token_with_oracle(
    db: Session,
    oracle: JupiterPriceOracle,
    account_id: int,
    token_mint: str,
    value_sol: float,
    slippage_percent: float = 0.5,
    fee_percent: float = 0.25,
    signal_score: float | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    quote = oracle.get_price(
        token_mint,
        force_refresh=True,
    )

    result = buy_paper_token(
        db=db,
        account_id=account_id,
        token_mint=token_mint,
        value_sol=value_sol,
        market_price_sol=(
            quote.sol_price
        ),
        slippage_percent=(
            slippage_percent
        ),
        fee_percent=fee_percent,
        signal_score=signal_score,
        reason=reason,
    )

    return {
        **result,
        "price": _quote_payload(
            quote
        ),
    }


def sell_paper_token_with_oracle(
    db: Session,
    oracle: JupiterPriceOracle,
    account_id: int,
    token_mint: str,
    quantity: float | None = None,
    slippage_percent: float = 0.5,
    fee_percent: float = 0.25,
    signal_score: float | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    quote = oracle.get_price(
        token_mint,
        force_refresh=True,
    )

    result = sell_paper_token(
        db=db,
        account_id=account_id,
        token_mint=token_mint,
        market_price_sol=(
            quote.sol_price
        ),
        quantity=quantity,
        slippage_percent=(
            slippage_percent
        ),
        fee_percent=fee_percent,
        signal_score=signal_score,
        reason=reason,
    )

    return {
        **result,
        "price": _quote_payload(
            quote
        ),
    }


def refresh_paper_account_prices(
    db: Session,
    oracle: JupiterPriceOracle,
    account_id: int,
    force_refresh: bool = False,
) -> dict[str, Any]:
    account = get_paper_account(
        db,
        account_id,
    )

    positions = (
        db.query(PaperPosition)
        .filter(
            PaperPosition.account_id
            == account.id,
            PaperPosition.status
            == "OPEN",
        )
        .with_for_update()
        .all()
    )

    if not positions:
        return {
            "account_id": account.id,
            "updated_positions": [],
            "prices": [],
            "missing_token_mints": [],
            "summary": (
                get_paper_account_summary(
                    db,
                    account.id,
                )
            ),
            "refreshed_at": (
                datetime.now(
                    timezone.utc
                )
            ),
        }

    token_mints = [
        position.token_mint
        for position in positions
    ]

    batch = oracle.get_prices(
        token_mints,
        force_refresh=force_refresh,
    )

    updated_positions: list[
        PaperPosition
    ] = []

    for position in positions:
        quote = batch.prices.get(
            position.token_mint
        )

        if quote is None:
            continue

        position.last_price_sol = (
            quote.sol_price
        )

        position.market_value_sol = (
            float(
                position.quantity
                or 0.0
            )
            * quote.sol_price
        )

        position.unrealized_pnl_sol = (
            float(
                position.market_value_sol
                or 0.0
            )
            - float(
                position.cost_basis_sol
                or 0.0
            )
        )

        updated_positions.append(
            position
        )

    try:
        db.commit()

    except Exception:
        db.rollback()
        raise

    for position in updated_positions:
        db.refresh(position)

    return {
        "account_id": account.id,
        "updated_positions": (
            updated_positions
        ),
        "prices": [
            _quote_payload(
                batch.prices[mint]
            )
            for mint in token_mints
            if mint in batch.prices
        ],
        "missing_token_mints": (
            batch.missing_token_mints
        ),
        "summary": (
            get_paper_account_summary(
                db,
                account.id,
            )
        ),
        "refreshed_at": (
            batch.fetched_at
        ),
    } 