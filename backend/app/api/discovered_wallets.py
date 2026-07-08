from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.database.session import get_db
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.schemas.discovered_wallet import DiscoveredWalletResponse

router = APIRouter(
    prefix="/discovered-wallets",
    tags=["Discovered Wallets"],
)


@router.get("", response_model=list[DiscoveredWalletResponse])
def get_discovered_wallets(
    min_score: float = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return (
        db.query(DiscoveredWallet)
        .filter(DiscoveredWallet.smart_score >= min_score)
        .order_by(DiscoveredWallet.smart_score.desc())
        .limit(limit)
        .all()
    )


@router.get("/{wallet_address}", response_model=DiscoveredWalletResponse)
def get_discovered_wallet(
    wallet_address: str,
    db: Session = Depends(get_db),
):
    wallet = (
        db.query(DiscoveredWallet)
        .filter(DiscoveredWallet.wallet_address == wallet_address)
        .first()
    )

    if wallet is None:
        raise HTTPException(
            status_code=404,
            detail="Wallet not found",
        )

    return wallet 