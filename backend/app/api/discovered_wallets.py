from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, case, desc
from sqlalchemy.orm import Session

from backend.app.database.session import get_db
from backend.app.schemas.candidate_backtest import (
    CandidateBacktestRequest,
    CandidateBacktestResponse,
    CandidateReconstructionAuditRequest,
    CandidateReconstructionAuditResponse,
    CandidatePositionLifecycleAuditRequest,
    CandidatePositionLifecycleAuditResponse,
    CandidateExitPriceAuditRequest,
    CandidateExitPriceAuditResponse,
    CandidateExitabilityRefreshRequest,
    CandidateExitabilityRefreshResponse,
    CandidateHistoryBackfillRequest,
    CandidateHistoryBackfillResponse,
)
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.schemas.discovered_wallet import (
    DiscoveryHydrationResponse,
    DiscoveredWalletActivityRefreshResponse,
    DiscoveredWalletQualityRefreshResponse,
    DiscoveredWalletResponse,
    CandidateExitabilityGateResponse,
    CandidateDiscoveryFunnelResponse,
    Gen4CopyabilityAwareDiscoveryPreviewResponse,
)
from backend.app.services.candidate_backtest_service import (
    get_latest_candidate_backtest,
    run_candidate_backtest,
)

from backend.app.services.candidate_reconstruction_audit_service import (
    get_latest_candidate_reconstruction_audit,
    run_candidate_reconstruction_audit,
)
from backend.app.services.candidate_position_lifecycle_audit_service import (
    get_latest_candidate_position_lifecycle_audit,
    run_candidate_position_lifecycle_audit,
)
from backend.app.services.candidate_exit_price_audit_service import (
    get_latest_candidate_exit_price_audit,
    run_candidate_exit_price_audit,
)
from backend.app.services.candidate_exitability_refresh_service import (
    refresh_candidate_open_position_exitability,
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
from backend.app.services.candidate_exitability_gate_service import (
    run_exitability_gate_refresh,
)
from backend.app.services.candidate_discovery_funnel_service import (
    get_latest_candidate_discovery_funnel,
    run_candidate_discovery_funnel,
)
from backend.app.services.discovery_hydration_service import (
    HydrationAlreadyRunningError,
    run_controlled_discovery_hydration,
)
from backend.app.services.gen4_copyability_aware_discovery_service import (
    M66_DEFAULT_POLICY,
    build_cached_discovery_snapshot,
    evaluate_copyability_aware_discovery,
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
    exit_price: Literal[
        "ALL",
        "READY",
        "PARTIAL",
        "BLOCKED",
        "NON_ANALIZZATO",
    ] = "ALL",
    exitability_gate: Literal[
        "ALL",
        "READY",
        "REVIEW",
        "BLOCKED",
        "NON_ANALIZZATO",
    ] = "ALL",
    discovery_funnel: Literal[
        "ALL",
        "READY",
        "REVIEW",
        "BLOCKED",
        "NEEDS_LOCAL_DATA",
        "NEEDS_HISTORY",
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
        "exit_price_coverage_score",
        "exit_price_local_observable_percent",
        "exit_price_current_route_percent",
        "discovery_funnel_score",
        "discovery_funnel_priority",
        "discovery_funnel_history_budget",
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
    if exit_price != "ALL":
        query = query.filter(
            DiscoveredWallet.exit_price_coverage_status == exit_price
        )
    if exitability_gate != "ALL":
        query = query.filter(
            DiscoveredWallet.exitability_gate_status == exitability_gate
        )
    if discovery_funnel != "ALL":
        query = query.filter(
            DiscoveredWallet.discovery_funnel_status == discovery_funnel
        )

    if sort_by == "discovery_funnel_priority":
        priority_order = case(
            (DiscoveredWallet.discovery_funnel_priority <= 0, 999999),
            else_=DiscoveredWallet.discovery_funnel_priority,
        )
        return (
            query.order_by(
                desc(DiscoveredWallet.eligible),
                asc(priority_order),
                desc(DiscoveredWallet.discovery_funnel_score),
                desc(DiscoveredWallet.smart_score),
            )
            .limit(limit)
            .all()
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


@router.post(
    "/promotion/audit",
    response_model=CandidateReconstructionAuditResponse,
)
def run_reconstruction_audit(
    request: CandidateReconstructionAuditRequest,
    db: Session = Depends(get_db),
):
    try:
        return run_candidate_reconstruction_audit(
            db,
            **request.model_dump(),
        )
    except ValueError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error


@router.get(
    "/promotion/audit/{wallet_address}/latest",
    response_model=CandidateReconstructionAuditResponse,
)
def read_latest_reconstruction_audit(
    wallet_address: str,
    db: Session = Depends(get_db),
):
    run = get_latest_candidate_reconstruction_audit(
        db,
        wallet_address,
    )

    if run is None:
        raise HTTPException(
            status_code=404,
            detail="Audit ricostruzione non trovato",
        )

    return run


@router.post(
    "/promotion/lifecycle-audit",
    response_model=(
        CandidatePositionLifecycleAuditResponse
    ),
)
def run_position_lifecycle_audit(
    request: (
        CandidatePositionLifecycleAuditRequest
    ),
    db: Session = Depends(get_db),
):
    try:
        return (
            run_candidate_position_lifecycle_audit(
                db,
                **request.model_dump(),
            )
        )
    except ValueError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error


@router.get(
    (
        "/promotion/lifecycle-audit/"
        "{wallet_address}/latest"
    ),
    response_model=(
        CandidatePositionLifecycleAuditResponse
    ),
)
def read_latest_position_lifecycle_audit(
    wallet_address: str,
    db: Session = Depends(get_db),
):
    run = (
        get_latest_candidate_position_lifecycle_audit(
            db,
            wallet_address,
        )
    )

    if run is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Audit lifecycle posizioni "
                "non trovato"
            ),
        )

    return run


@router.post(
    "/promotion/exit-price-audit",
    response_model=CandidateExitPriceAuditResponse,
)
def run_exit_price_audit(
    request: CandidateExitPriceAuditRequest,
    db: Session = Depends(get_db),
):
    try:
        return run_candidate_exit_price_audit(
            db,
            **request.model_dump(),
        )
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from error


@router.post(
    "/promotion/exitability-refresh",
    response_model=CandidateExitabilityRefreshResponse,
)
def refresh_open_position_exitability(
    request: CandidateExitabilityRefreshRequest,
    db: Session = Depends(get_db),
):
    try:
        return refresh_candidate_open_position_exitability(
            db,
            **request.model_dump(),
        )
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from error


@router.get(
    "/promotion/exit-price-audit/{wallet_address}/latest",
    response_model=CandidateExitPriceAuditResponse,
)
def read_latest_exit_price_audit(
    wallet_address: str,
    db: Session = Depends(get_db),
):
    run = get_latest_candidate_exit_price_audit(
        db,
        wallet_address,
    )
    if run is None:
        raise HTTPException(
            status_code=404,
            detail="Audit copertura prezzi di uscita non trovato",
        )
    return run


@router.post(
    "/exitability-gate/refresh",
    response_model=CandidateExitabilityGateResponse,
)
def refresh_exitability_gate(
    limit: int = Query(default=250, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return run_exitability_gate_refresh(db, limit=limit)


@router.post(
    "/candidate-funnel/refresh",
    response_model=CandidateDiscoveryFunnelResponse,
)
def refresh_candidate_discovery_funnel(
    limit: int = Query(default=500, ge=1, le=500),
    history_request_budget: int = Query(default=10, ge=0, le=50),
    max_history_wallets: int = Query(default=5, ge=1, le=20),
    target_history_days: int = Query(default=30, ge=7, le=90),
    db: Session = Depends(get_db),
):
    return run_candidate_discovery_funnel(
        db,
        limit=limit,
        history_request_budget=history_request_budget,
        max_history_wallets=max_history_wallets,
        target_history_days=target_history_days,
    )


@router.get(
    "/candidate-funnel/latest",
    response_model=CandidateDiscoveryFunnelResponse,
)
def read_latest_candidate_discovery_funnel(
    db: Session = Depends(get_db),
):
    run = get_latest_candidate_discovery_funnel(db)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail="Candidate funnel non trovato",
        )
    return run


@router.get(
    "/definitive-discovery/preview",
    response_model=Gen4CopyabilityAwareDiscoveryPreviewResponse,
)
def preview_gen4_copyability_aware_discovery(
    limit: int = Query(default=500, ge=1, le=500),
    maximum_selected_wallets: int = Query(default=3, ge=1, le=3),
    db: Session = Depends(get_db),
):
    """M66 cached-only preview: GET, zero writes and zero provider calls."""
    policy = {
        **M66_DEFAULT_POLICY,
        "maximum_selected_wallets": maximum_selected_wallets,
    }
    snapshot = build_cached_discovery_snapshot(
        db,
        limit=limit,
        policy=policy,
    )
    return evaluate_copyability_aware_discovery(
        snapshot,
        policy=policy,
    )


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
