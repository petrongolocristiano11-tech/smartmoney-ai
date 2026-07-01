from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.database.session import get_db
from backend.app.models.wallet import Wallet
from backend.app.schemas.wallet import WalletCreate, WalletResponse

router = APIRouter(
    prefix="/wallets",
    tags=["Wallets"],
)


@router.post("")
def create_wallet(
    wallet: WalletCreate,
    db: Session = Depends(get_db),
):
    new_wallet = Wallet(address=wallet.address)

    db.add(new_wallet)
    db.commit()
    db.refresh(new_wallet)

    return {
        "id": new_wallet.id,
        "address": new_wallet.address,
        "message": "Wallet creato con successo",
    }


@router.get("", response_model=list[WalletResponse])
def get_wallets(
    db: Session = Depends(get_db),
):
    return db.query(Wallet).all()


@router.get("/{wallet_id}", response_model=WalletResponse | None)
def get_wallet(
    wallet_id: int,
    db: Session = Depends(get_db),
):
    return db.query(Wallet).filter(
        Wallet.id == wallet_id
    ).first()


@router.delete("/{wallet_id}")
def delete_wallet(
    wallet_id: int,
    db: Session = Depends(get_db),
):
    wallet = db.query(Wallet).filter(
        Wallet.id == wallet_id
    ).first()

    if wallet is None:
        return {
            "message": "Wallet non trovato",
        }

    db.delete(wallet)
    db.commit()

    return {
        "message": "Wallet eliminato con successo",
        "id": wallet_id,
    } 