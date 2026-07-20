from sqlalchemy.orm import Session

from backend.app.models.live_copy_order import LiveCopyOrder


MANUAL_DRY_RUN_CLOSE_WALLET = "MANUAL_DRY_RUN_CLOSE"
COMPLETED_ORDER_STATUSES = ("DRY_RUN", "FILLED")


def is_manual_close_wallet(value: str | None) -> bool:
    return str(value or "").strip() == MANUAL_DRY_RUN_CLOSE_WALLET


def build_buy_source_wallet_lookup(
    db: Session,
    *,
    mode: str,
    generation: int,
) -> dict[str, str]:
    """Return the latest real source wallet for every bought token.

    A DRY_RUN manual close is an execution origin, not a source wallet. Existing
    manual-close orders are therefore attributed to the latest completed BUY of
    the same token in the same mode/generation.
    """
    rows = (
        db.query(LiveCopyOrder)
        .filter(
            LiveCopyOrder.mode == mode,
            LiveCopyOrder.generation == generation,
            LiveCopyOrder.source_side == "BUY",
            LiveCopyOrder.status.in_(COMPLETED_ORDER_STATUSES),
            LiveCopyOrder.source_wallet != MANUAL_DRY_RUN_CLOSE_WALLET,
        )
        .order_by(LiveCopyOrder.created_at.asc(), LiveCopyOrder.id.asc())
        .all()
    )

    lookup: dict[str, str] = {}
    for order in rows:
        token_mint = str(order.source_token_mint or "").strip()
        wallet = str(order.source_wallet or "").strip()
        if token_mint and wallet:
            lookup[token_mint] = wallet
    return lookup


def resolve_order_source_wallet(
    order: LiveCopyOrder,
    buy_source_wallet_lookup: dict[str, str],
) -> str:
    wallet = str(order.source_wallet or "").strip()
    if not is_manual_close_wallet(wallet):
        return wallet or "UNKNOWN"

    token_mint = str(order.source_token_mint or "").strip()
    return buy_source_wallet_lookup.get(token_mint, wallet or "UNKNOWN")


def find_latest_buy_source_wallet(
    db: Session,
    *,
    mode: str,
    generation: int,
    token_mint: str,
) -> str | None:
    row = (
        db.query(LiveCopyOrder)
        .filter(
            LiveCopyOrder.mode == mode,
            LiveCopyOrder.generation == generation,
            LiveCopyOrder.source_side == "BUY",
            LiveCopyOrder.source_token_mint == token_mint,
            LiveCopyOrder.status.in_(COMPLETED_ORDER_STATUSES),
            LiveCopyOrder.source_wallet != MANUAL_DRY_RUN_CLOSE_WALLET,
        )
        .order_by(LiveCopyOrder.executed_at.desc(), LiveCopyOrder.id.desc())
        .first()
    )
    if row is None:
        return None
    wallet = str(row.source_wallet or "").strip()
    return wallet or None
