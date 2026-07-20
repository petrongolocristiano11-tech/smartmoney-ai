from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.app.core.live_trading_security import require_live_trading_key
from backend.app.database.session import get_db
from backend.app.models.token_safety_snapshot import TokenSafetySnapshot
from backend.app.schemas.live_platform import (
    ApplySmartWalletsRequest,
    ApplySmartWalletsResponse,
    LiveArmRequest,
    LiveArmResponse,
    LivePlatformConfigResponse,
    LivePlatformConfigUpdateRequest,
    LiveReadinessResponse,
    LiveTradingAnalyticsResponse,
    LiveWalletRankingResponse,
    TokenSafetyListResponse,
    TokenSafetySnapshotResponse,
)
from backend.app.services.jupiter_swap_client import JupiterSwapClient
from backend.app.services.live_platform_config_service import (
    get_or_create_platform_config,
    update_platform_config,
)
from backend.app.services.live_readiness_service import (
    arm_live_platform,
    build_live_readiness,
    disarm_live,
)
from backend.app.services.live_trading_analytics import (
    build_live_trading_analytics,
    build_live_trading_csv,
)
from backend.app.services.live_trading_errors import LiveTradingError
from backend.app.services.live_wallet_ranking_service import (
    apply_ranked_wallets,
    list_live_wallet_ranking,
    refresh_live_wallet_ranking,
)
from backend.app.services.solana_rpc import SolanaRpcClient
from backend.app.services.solana_transaction_signer import SolanaTransactionSigner
from backend.app.services.token_safety_service import (
    DexScreenerClient,
    RugCheckClient,
    refresh_token_safety_snapshot,
)


router = APIRouter(
    prefix="/live-trading/platform",
    tags=["Live Trading Platform"],
    dependencies=[Depends(require_live_trading_key)],
)


def get_rpc_client() -> SolanaRpcClient:
    return SolanaRpcClient()


def get_signer() -> SolanaTransactionSigner:
    return SolanaTransactionSigner()


def get_jupiter_client() -> JupiterSwapClient:
    return JupiterSwapClient()


def get_dex_client() -> DexScreenerClient:
    return DexScreenerClient()


def get_rugcheck_client() -> RugCheckClient:
    return RugCheckClient()


def raise_platform_http_error(error: LiveTradingError) -> None:
    raise HTTPException(
        status_code=error.status_code,
        detail={
            "code": error.code,
            "message": error.message,
            "payload": error.payload,
        },
    ) from error


@router.get("/config", response_model=LivePlatformConfigResponse)
def read_platform_config(db: Session = Depends(get_db)):
    return get_or_create_platform_config(db)


@router.patch("/config", response_model=LivePlatformConfigResponse)
def patch_platform_config(
    payload: LivePlatformConfigUpdateRequest,
    db: Session = Depends(get_db),
):
    try:
        return update_platform_config(
            db,
            get_or_create_platform_config(db),
            payload.model_dump(exclude_unset=True),
        )
    except LiveTradingError as error:
        raise_platform_http_error(error)


@router.get("/analytics", response_model=LiveTradingAnalyticsResponse)
def read_platform_analytics(
    days: int = Query(default=30, ge=1, le=365),
    mode: Literal["DRY_RUN", "LIVE"] = "DRY_RUN",
    generation: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
):
    return build_live_trading_analytics(
        db,
        days=days,
        mode=mode,
        generation=generation,
    )


@router.get("/analytics/export.csv")
def export_platform_analytics_csv(
    days: int = Query(default=30, ge=1, le=365),
    mode: Literal["DRY_RUN", "LIVE"] = "DRY_RUN",
    generation: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
):
    payload = build_live_trading_analytics(
        db,
        days=days,
        mode=mode,
        generation=generation,
    )
    csv_content = build_live_trading_csv(payload)
    filename = f"smartmoney-live-analytics-{mode.lower()}-g{payload['generation']}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/wallet-ranking", response_model=LiveWalletRankingResponse)
def read_wallet_ranking(
    refresh: bool = False,
    db: Session = Depends(get_db),
):
    ranking = list_live_wallet_ranking(db, refresh=refresh)
    return {
        "count": len(ranking),
        "eligible_count": sum(1 for row in ranking if row.eligible),
        "ranking": ranking,
    }


@router.post("/wallet-ranking/refresh", response_model=LiveWalletRankingResponse)
def refresh_wallet_ranking(db: Session = Depends(get_db)):
    ranking = refresh_live_wallet_ranking(db)
    return {
        "count": len(ranking),
        "eligible_count": sum(1 for row in ranking if row.eligible),
        "ranking": ranking,
    }


@router.post("/wallet-ranking/apply", response_model=ApplySmartWalletsResponse)
def apply_wallet_ranking(
    payload: ApplySmartWalletsRequest,
    db: Session = Depends(get_db),
):
    try:
        return apply_ranked_wallets(
            db,
            confirmation=payload.confirmation,
            limit=payload.limit,
        )
    except LiveTradingError as error:
        raise_platform_http_error(error)


@router.get("/token-safety", response_model=TokenSafetyListResponse)
def list_token_safety(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    snapshots = (
        db.query(TokenSafetySnapshot)
        .order_by(TokenSafetySnapshot.fetched_at.desc())
        .limit(limit)
        .all()
    )
    return {"count": len(snapshots), "snapshots": snapshots}


@router.post(
    "/token-safety/{token_mint}/refresh",
    response_model=TokenSafetySnapshotResponse,
)
def refresh_token_safety(
    token_mint: str,
    db: Session = Depends(get_db),
    rpc_client: SolanaRpcClient = Depends(get_rpc_client),
    jupiter_client: JupiterSwapClient = Depends(get_jupiter_client),
    dex_client: DexScreenerClient = Depends(get_dex_client),
    rugcheck_client: RugCheckClient = Depends(get_rugcheck_client),
):
    try:
        return refresh_token_safety_snapshot(
            db,
            token_mint=token_mint,
            rpc_client=rpc_client,
            jupiter_client=jupiter_client,
            dex_client=dex_client,
            rugcheck_client=rugcheck_client,
        )
    except LiveTradingError as error:
        raise_platform_http_error(error)


@router.get("/readiness", response_model=LiveReadinessResponse)
def read_live_readiness(
    db: Session = Depends(get_db),
    rpc_client: SolanaRpcClient = Depends(get_rpc_client),
    signer: SolanaTransactionSigner = Depends(get_signer),
):
    return build_live_readiness(db, rpc_client=rpc_client, signer=signer)


@router.post("/live/arm", response_model=LiveArmResponse)
def arm_live(
    payload: LiveArmRequest,
    db: Session = Depends(get_db),
    rpc_client: SolanaRpcClient = Depends(get_rpc_client),
    signer: SolanaTransactionSigner = Depends(get_signer),
):
    try:
        return arm_live_platform(
            db,
            confirmation=payload.confirmation,
            rpc_client=rpc_client,
            signer=signer,
        )
    except LiveTradingError as error:
        raise_platform_http_error(error)


@router.post("/live/disarm", response_model=LiveArmResponse)
def disarm_live_execution(db: Session = Depends(get_db)):
    return disarm_live(db)
