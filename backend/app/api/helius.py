from fastapi import APIRouter

from backend.app.services.helius import get_helius_health

router = APIRouter(
    prefix="/helius",
    tags=["Helius"],
)


@router.get("/health")
def helius_health():
    return get_helius_health() 