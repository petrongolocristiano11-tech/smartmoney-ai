from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.app.database.session import get_db
from backend.app.schemas.candidate_backtest import (
    CandidateBacktestRequest,
    CandidateBacktestResponse,
    CandidateHistoryBackfillRequest,
    CandidateHistoryBackfillResponse,
)
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.schemas.discovered_wallet import (
    DiscoveryHydrationResponse,
    DiscoveredWalletActivityRefreshResponse,
    DiscoveredWalletQualityRefreshResponse,
    DiscoveredWalletResponse,
)
from backend.app.services.candidate_backtest_service import (
    get_latest_candidate_backtest,
    run_candidate_backtest,
)
from backend.app.services.candidate_history_service import (
    CandidateHistoryAlreadyRunningError,
    get_latest_extended_candidate_history,
    run_extended_candidate_history,
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
    promotion: Literal[
        "ALL",
        "PROMOSSO",
        "OSSERVAZIONE",
        "BOCCIATO",
        "DATI_INSUFFICIENTI",
        "NON_ANALIZZATO",
    ] = "ALL",
    sort_by: Literal[
        "ranking_score",
        "smart_score",
        "activity_score",
        "quality_score",
        "backtest_score",
        "backtest_data_sufficiency_score",
        "backtest_total_return_percent",
        "backtest_max_drawdown_percent",
        "backtest_jupiter_compatibility_percent",
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
    if promotion != "ALL":
        query = query.filter(DiscoveredWallet.promotion_status == promotion)

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


@router.post(
    "/promotion/history/backfill",
    response_model=CandidateHistoryBackfillResponse,
)
def run_candidate_history_backfill(
    request: CandidateHistoryBackfillRequest,
    db: Session = Depends(get_db),
):
    try:
        return run_extended_candidate_history(db, **request.model_dump())
    except CandidateHistoryAlreadyRunningError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get(
    "/promotion/history/{wallet_address}/latest",
    response_model=CandidateHistoryBackfillResponse,
)
def read_latest_candidate_history_backfill(
    wallet_address: str,
    db: Session = Depends(get_db),
):
    run = get_latest_extended_candidate_history(db, wallet_address)
    if run is None:
        raise HTTPException(status_code=404, detail="Backfill storico non trovato")
    return run


@router.post(
    "/promotion/backtest",
    response_model=CandidateBacktestResponse,
)
def run_promotion_backtest(
    request: CandidateBacktestRequest,
    db: Session = Depends(get_db),
):
    try:
        return run_candidate_backtest(db, **request.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get(
    "/promotion/{wallet_address}/latest",
    response_model=CandidateBacktestResponse,
)
def read_latest_promotion_backtest(
    wallet_address: str,
    db: Session = Depends(get_db),
):
    run = get_latest_candidate_backtest(db, wallet_address)
    if run is None:
        raise HTTPException(status_code=404, detail="Backtest non trovato")
    return run


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
