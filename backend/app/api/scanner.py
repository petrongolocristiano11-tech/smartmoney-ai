from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.database.session import get_db
from backend.app.services.dashboard_service import get_dashboard
from backend.app.services.solana_rpc import (
    analyze_wallet,
    get_wallet_transactions,
)

router = APIRouter(
    prefix="/scanner",
    tags=["Scanner"],
)

@router.get("/dashboard")
def dashboard(
    db: Session = Depends(get_db),
):
    return get_dashboard(db)

@router.get("/analyze/{address}")
def analyze(address: str):
    return analyze_wallet(address)
 

@router.get("/{address}")
def scan_wallet(address: str):
    transactions = get_wallet_transactions(
        address,
        limit=10,
    )

    return {
        "wallet": address,
        "transactions_found": len(transactions),
        "transactions": transactions,
    }




