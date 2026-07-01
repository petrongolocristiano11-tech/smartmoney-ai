from fastapi import APIRouter

from backend.app.services.solana_rpc import (
    get_solana_health,
    get_wallet_balance,
    get_wallet_transactions,
    get_transaction_detail,
)

router = APIRouter(
    prefix="/solana",
    tags=["Solana"],
)


@router.get("/health")
def solana_health():
    return get_solana_health()


@router.get("/balance/{address}")
def solana_balance(address: str):
    return get_wallet_balance(address)


@router.get("/transactions/{address}")
def solana_transactions(address: str):
    return get_wallet_transactions(address)


@router.get("/transaction/{signature}")
def solana_transaction(signature: str):
    return get_transaction_detail(signature) 