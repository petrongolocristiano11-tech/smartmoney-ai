from fastapi import APIRouter

from backend.app.services.solana_rpc import (
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