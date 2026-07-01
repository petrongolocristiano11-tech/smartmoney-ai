from fastapi import APIRouter

from backend.app.services.solana_rpc import (
    analyze_wallet,
    get_wallet_transactions,
)

router = APIRouter(
    prefix="/scanner",
    tags=["Scanner"],
)


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


@router.get("/analyze/{address}")
def analyze(address: str):
    return analyze_wallet(address) 