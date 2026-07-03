from datetime import datetime, UTC

from sqlalchemy.orm import Session

from backend.app.models.wallet import Wallet


def update_wallet_last_sync(
    db: Session,
    wallet_address: str,
):
    wallet = (
        db.query(Wallet)
        .filter(Wallet.address == wallet_address)
        .first()
    )

    if wallet is None:
        return

    wallet.last_sync = datetime.now(UTC)

    db.commit() 