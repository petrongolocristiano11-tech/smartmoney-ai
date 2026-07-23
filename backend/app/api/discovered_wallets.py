from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.app.database.session import get_db
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.schemas.discovered_wallet import (
    DiscoveryHydrationResponse,
    DiscoveredWalletActivityRefreshResponse,
    DiscoveredWalletQualityRefreshResponse,
    DiscoveredWalletResponse,
)
from backend.app.services.discovered_wallet_service import (
    refresh_discovered_wallet_activity,
    refresh_discovered_wallet_quality,
)
from backend.app.services.discovery_hydration_service import (
    HydrationAlreadyRunningError,
    run_controlled_discovery_hydration,
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
    quality: Literal[
        "ALL",
        "COPIABILE",
        "OSSERVAZIONE",
        "SOSPETTO",
        "NON_COPIABILE",
        "NON_ANALIZZATO",
    ] = "ALL",
    sort_by: Literal[
        "ranking_score",
        "smart_score",
        "activity_score",
        "quality_score",
        "median_swap_sol_7d",
        "size_compatibility_ratio_7d",
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
    if quality != "ALL":
        query = query.filter(
            DiscoveredWallet.quality_classification == quality
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


@router.post(
    "/quality/refresh",
    response_model=DiscoveredWalletQualityRefreshResponse,
)
def refresh_quality_ranking(
    limit: int = Query(default=250, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return refresh_discovered_wallet_quality(db, limit=limit)


@router.post(
    "/hydration/run",
    response_model=DiscoveryHydrationResponse,
)
def run_discovery_hydration(
    max_wallets: int = Query(default=3, ge=1, le=10),
    max_helius_requests: int = Query(default=3, ge=1, le=10),
    lookback_days: int = Query(default=7, ge=1, le=14),
    transaction_limit: int = Query(default=100, ge=1, le=100),
    minimum_smart_score: float = Query(default=0, ge=0, le=100),
    force: bool = False,
    db: Session = Depends(get_db),
):
    try:
        return run_controlled_discovery_hydration(
            db,
            max_wallets=max_wallets,
            max_helius_requests=max_helius_requests,
            lookback_days=lookback_days,
            transaction_limit=transaction_limit,
            minimum_smart_score=minimum_smart_score,
            force=force,
        )
    except HydrationAlreadyRunningError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


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
