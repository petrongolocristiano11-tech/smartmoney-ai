from fastapi import APIRouter

from backend.app.services.helius import (
    get_helius_health,
    get_enhanced_transaction,
    get_wallet_history,
    get_wallet_swaps,
)

router = APIRouter(
    prefix="/helius",
    tags=["Helius"],
)


@router.get("/health")
def helius_health():
    return get_helius_health()


@router.get("/transaction/{signature}")
def helius_transaction(signature: str):
    return get_enhanced_transaction(signature)


@router.get("/wallet/{address}")
def helius_wallet(address: str):
    return get_wallet_history(address)


@router.get("/wallet/{address}/swaps")
def helius_wallet_swaps(address: str):
    return get_wallet_swaps(address) 