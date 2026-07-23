from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.app.database.session import get_db
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.schemas.discovered_wallet import (
    DiscoveredWalletActivityRefreshResponse,
    DiscoveredWalletResponse,
)
from backend.app.services.discovered_wallet_service import (
    refresh_discovered_wallet_activity,
)


router = APIRouter(
    prefix="/discovered-wallets",
    tags=["Discovered Wallets"],
)


@router.get("", response_model=list[DiscoveredWalletResponse])
def get_discovered_wallets(
    min_score: float = Query(default=0, ge=0, le=100),
    limit: int = Query(default=100, ge=1, le=500),
    eligible_only: bool = False,
    activity: Literal[
        "ALL",
        "ATTIVO",
        "POCO_ATTIVO",
        "INATTIVO",
        "IPERATTIVO",
        "NON_ANALIZZATO",
    ] = "ALL",
    sort_by: Literal[
        "ranking_score",
        "smart_score",
        "activity_score",
        "last_swap_at",
        "volume_7d_sol",
    ] = "ranking_score",
    db: Session = Depends(get_db),
):
    query = db.query(DiscoveredWallet).filter(
        DiscoveredWallet.smart_score >= min_score
    )

    if eligible_only:
        query = query.filter(DiscoveredWallet.eligible.is_(True))
    if activity != "ALL":
        query = query.filter(
            DiscoveredWallet.activity_classification == activity
        )

    order_column = getattr(DiscoveredWallet, sort_by)
    return (
        query.order_by(
            desc(DiscoveredWallet.eligible),
            desc(order_column),
            desc(DiscoveredWallet.smart_score),
        )
        .limit(limit)
        .all()
    )


@router.post(
    "/activity/refresh",
    response_model=DiscoveredWalletActivityRefreshResponse,
)
def refresh_activity_ranking(
    limit: int = Query(default=250, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return refresh_discovered_wallet_activity(db, limit=limit)


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
        raise HTTPException(status_code=404, detail="Wallet not found")

    return wallet
