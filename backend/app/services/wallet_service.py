from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.app.models.wallet import Wallet


def update_wallet_last_sync(
    db: Session,
    wallet_address: str,
):
    wallet = (
        db.query(Wallet)
        .filter(
            Wallet.address
            == wallet_address
        )
        .first()
    )

    current_time = datetime.now(UTC)

    if wallet is None:
        wallet = Wallet(
            address=wallet_address,
            last_sync=current_time,
        )

        db.add(wallet)
    else:
        wallet.last_sync = current_time

    db.commit()
    db.refresh(wallet)

    return wallet 