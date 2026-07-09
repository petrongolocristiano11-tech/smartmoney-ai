from sqlalchemy.orm import Session

from backend.app.models.wallet import Wallet
from backend.app.services.cache_engine import needs_sync
from backend.app.services.helius import get_wallet_swaps
from backend.app.services.smart_score_engine import calculate_smart_score
from backend.app.services.trade_engine import build_trade, build_trade_data
from backend.app.services.trade_service import create_trade_if_not_exists
from backend.app.services.wallet_service import update_wallet_last_sync


def sync_wallet(db: Session, wallet_address: str):
    """
    Sincronizza un wallet.

    - usa cache se possibile
    - importa gli swap se necessario
    - aggiorna Smart Score
    - aggiorna last_sync
    """

    wallet = (
        db.query(Wallet)
        .filter(Wallet.address == wallet_address)
        .first()
    )

    if wallet and not needs_sync(wallet):
        return calculate_smart_score(db, wallet_address)

    swaps = get_wallet_swaps(wallet_address)

    for swap in swaps["swaps"]:
        trade = build_trade(swap)
        trade_data = build_trade_data(wallet_address, trade)
        create_trade_if_not_exists(db, trade_data)

    update_wallet_last_sync(
        db,
        wallet_address,
    )

    return calculate_smart_score(
        db,
        wallet_address,
    ) 
