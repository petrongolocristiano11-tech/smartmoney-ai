from fastapi import APIRouter

from backend.app.services.helius import (
    get_helius_health,
    get_enhanced_transaction,
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