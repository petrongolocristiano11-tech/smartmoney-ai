import json
from dataclasses import dataclass
from datetime import (
    datetime,
    timezone,
)
from typing import Callable

from sqlalchemy.orm import Session

from backend.app.database.session import (
    SessionLocal,
)
from backend.app.services.helius import (
    get_enhanced_transaction,
)
from backend.app.services.live_copy_trading_engine import (
    execute_source_trade,
)
from backend.app.services.trade_engine import (
    build_trade,
    build_trade_data,
    normalize_swap,
)
from backend.app.services.trade_service import (
    create_trade_if_not_exists,
)


@dataclass(frozen=True)
class LiveStreamProcessResult:
    signature: str
    wallet_address: str
    outcome: str
    message: str
    trade_id: int | None = None
    order_id: int | None = None
    order_mode: str | None = None
    order_status: str | None = None


def timestamp_to_datetime(
    value,
) -> datetime | None:
    if value in (
        None,
        "",
    ):
        return None

    try:
        return datetime.fromtimestamp(
            int(value),
            tz=timezone.utc,
        )

    except (
        TypeError,
        ValueError,
        OSError,
    ):
        return None


def process_live_signature(
    signature: str,
    expected_wallet: str,
    *,
    session_factory=SessionLocal,
    enhanced_transaction_provider: (
        Callable[[str], list]
        | None
    ) = None,
    order_executor=None,
) -> LiveStreamProcessResult:
    normalized_signature = str(
        signature
    ).strip()

    normalized_wallet = str(
        expected_wallet
    ).strip()

    if not normalized_signature:
        raise ValueError(
            "Signature Helius vuota."
        )

    if not normalized_wallet:
        raise ValueError(
            "Wallet sorgente vuoto."
        )

    executor = (
        order_executor
        or execute_source_trade
    )

    db: Session = session_factory()

    try:
        if enhanced_transaction_provider is None:
            transactions = get_enhanced_transaction(
                normalized_signature,
                request_origin="LEGACY_LIVE_STREAM",
                automatic=True,
            )
        else:
            transactions = enhanced_transaction_provider(
                normalized_signature
            )

        if not isinstance(
            transactions,
            list,
        ):
            return LiveStreamProcessResult(
                signature=normalized_signature,
                wallet_address=normalized_wallet,
                outcome="SKIPPED",
                message=(
                    "Risposta Helius non valida."
                ),
            )

        for transaction in transactions:
            if not isinstance(
                transaction,
                dict,
            ):
                continue

            normalized_swap = normalize_swap(
                transaction,
                wallet_address=(
                    normalized_wallet
                ),
            )

            trade = build_trade(
                normalized_swap
            )

            if (
                not trade
                or trade.get("side")
                not in {
                    "BUY",
                    "SELL",
                }
                or not trade.get(
                    "token_mint"
                )
            ):
                continue

            trade_data = build_trade_data(
                normalized_wallet,
                trade,
            )

            trade_data["block_time"] = (
                timestamp_to_datetime(
                    transaction.get(
                        "timestamp"
                    )
                )
            )

            trade_data["raw_json"] = (
                json.dumps(
                    trade,
                    default=str,
                    separators=(
                        ",",
                        ":",
                    ),
                )
            )

            stored_trade = (
                create_trade_if_not_exists(
                    db,
                    trade_data,
                )
            )

            order = executor(
                db,
                trade=stored_trade,
                origin="STREAM",
            )

            if order is None:
                return LiveStreamProcessResult(
                    signature=(
                        normalized_signature
                    ),
                    wallet_address=(
                        normalized_wallet
                    ),
                    outcome="IGNORED",
                    message=(
                        "Nessun ordine creato: "
                        "stream non eseguibile oppure "
                        "SELL senza posizione aperta."
                    ),
                    trade_id=stored_trade.id,
                )

            return LiveStreamProcessResult(
                signature=normalized_signature,
                wallet_address=normalized_wallet,
                outcome="ORDER",
                message=(
                    "Trade sorgente elaborato "
                    "dal motore copy-trading."
                ),
                trade_id=stored_trade.id,
                order_id=order.id,
                order_mode=order.mode,
                order_status=order.status,
            )

        return LiveStreamProcessResult(
            signature=normalized_signature,
            wallet_address=normalized_wallet,
            outcome="SKIPPED",
            message=(
                "La transazione non contiene "
                "uno swap compatibile del "
                "wallet sorgente."
            ),
        )

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()
