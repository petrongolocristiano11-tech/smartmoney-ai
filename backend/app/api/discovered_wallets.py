from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.database.session import get_db
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.schemas.discovered_wallet import DiscoveredWalletResponse

router = APIRouter(
    prefix="/discovered-wallets",
    tags=["Discovered Wallets"],
)


@router.get("", response_model=list[DiscoveredWalletResponse])
def get_discovered_wallets(db: Session = Depends(get_db)):
    return (
        db.query(DiscoveredWallet)
        .order_by(DiscoveredWallet.smart_score.desc())
        .all()
    ) 