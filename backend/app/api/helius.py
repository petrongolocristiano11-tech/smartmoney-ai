from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.database.session import get_db
from backend.app.services.helius import (
    get_enhanced_transaction,
    get_helius_health,
    get_wallet_history,
    get_wallet_swaps,
)
from backend.app.services.trade_engine import build_trade, build_trade_data
from backend.app.services.trade_service import create_trade_if_not_exists 

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


@router.get("/wallet/{address}/parsed-swaps")
def helius_wallet_parsed_swaps(address: str):
    swaps = get_wallet_swaps(address)

    parsed = []

    for swap in swaps["swaps"]:
        parsed.append(build_trade(swap))

    return {
        "wallet": address,
        "found": swaps["swaps_found"],
        "parsed": parsed,
    }


@router.post("/wallet/{address}/import-swaps")
def import_wallet_swaps(
    address: str,
    db: Session = Depends(get_db),
):
    swaps = get_wallet_swaps(address)

    imported = []

    for swap in swaps["swaps"]:
        trade = build_trade(swap)
        trade_data = build_trade_data(address, trade)
        saved_trade = create_trade_if_not_exists(db, trade_data)
        imported.append(saved_trade)

    return {
        "wallet": address,
        "found": swaps["swaps_found"],
        "imported": len(imported),
        "trades": imported,
    } 