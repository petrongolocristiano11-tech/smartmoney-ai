import logging
from contextlib import (
    asynccontextmanager,
)
from backend.app.services.live_trading_worker_runtime import (
    live_trading_worker_runtime,
)
from backend.app.services.live_position_monitor_runtime import (
    live_position_monitor_runtime,
)
from datetime import (
    datetime,
    timezone,
)
from time import perf_counter
from uuid import uuid4

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
)
from fastapi.middleware.cors import (
    CORSMiddleware,
)
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.app.api.discovered_wallets import (
    router as discovered_wallets_router,
)
from backend.app.api.helius import (
    router as helius_router,
)
from backend.app.api.live import (
    router as live_router,
)
from backend.app.api.live_trading import (
    router as live_trading_router,
)
from backend.app.api.live_platform import (
    router as live_platform_router,
)
from backend.app.api.live_operations import (
    router as live_operations_router,
)
from backend.app.api.paper_autopilot import (
    router as paper_autopilot_router,
)
from backend.app.api.paper_trading import (
    router as paper_trading_router,
)
from backend.app.api.scanner import (
    router as scanner_router,
)
from backend.app.api.solana import (
    router as solana_router,
)
from backend.app.api.tokens import (
    router as tokens_router,
)
from backend.app.api.trades import (
    router as trades_router,
)
from backend.app.api.wallets import (
    router as wallet_router,
)
from backend.app.core.discovery_security import require_automation_key
from backend.app.database.session import get_db
from backend.app.schemas.blockchain_integrity import (
    CanonicalMaterializationExecuteRequest,
    CanonicalParserPromotionApproveRequest,
    CanonicalParserPromotionRevokeRequest,
    CanonicalQualityAssessmentRequest,
    CanonicalShadowValidationExecuteRequest,
    NormalizationReplayExecuteRequest,
    RawCaptureRetentionPruneRequest,
)
from backend.app.services.blockchain_canonical_quality_gate_service import (
    CanonicalQualityGateError,
    execute_canonical_quality_assessment,
    get_canonical_quality_assessment,
    get_canonical_quality_gate_status,
    preview_canonical_quality_gate,
)
from backend.app.services.blockchain_parser_promotion_service import (
    CanonicalParserPromotionError,
    approve_parser_promotion,
    get_parser_promotion,
    get_parser_promotion_status,
    preview_parser_promotion,
    revoke_parser_promotion,
)
from backend.app.services.blockchain_canonical_shadow_service import (
    CanonicalShadowError,
    execute_canonical_materialization,
    execute_shadow_validation,
    get_canonical_shadow_status,
    get_shadow_validation_batch,
    preview_canonical_materialization,
    preview_shadow_validation,
)
from backend.app.services.blockchain_normalization_replay_service import (
    NormalizationReplayError,
    execute_normalization_replay,
    get_normalization_replay_batch,
    get_parser_registry_status,
    preview_normalization_replay,
)
from backend.app.services.raw_blockchain_capture_governance_service import (
    RawCaptureGovernanceError,
    get_raw_capture_readiness,
    preview_raw_capture_retention,
    prune_raw_capture_retention,
    run_raw_capture_canary,
)
from backend.app.services.raw_blockchain_capture_service import (
    get_raw_capture_status,
)
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.error_handlers import (
    register_exception_handlers,
)
from backend.app.core.logging_config import (
    configure_logging,
)
from backend.app.database.session import (
    engine,
)


configure_logging()

logger = logging.getLogger(
    "smartmoney.api"
)


def utc_timestamp() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


@asynccontextmanager
async def lifespan(
    app: FastAPI,
):
    logger.info(
        "application_starting name=%s "
        "version=%s environment=%s",
        settings.APP_NAME,
        settings.APP_VERSION,
        settings.ENVIRONMENT,
    )

    try:
        with engine.connect() as connection:
            connection.execute(
                text("SELECT 1")
            )

        logger.info(
            "database_startup_check=connected"
        )

    except SQLAlchemyError as exception:
        logger.warning(
            "database_startup_check=unavailable "
            "error_type=%s",
            type(exception).__name__,
        )

    await live_trading_worker_runtime.start()
    await live_position_monitor_runtime.start()

    try:
        yield

    finally:
        await live_position_monitor_runtime.stop()
        await live_trading_worker_runtime.stop()

        engine.dispose()

        logger.info(
            "application_stopped name=%s",
            settings.APP_NAME,
        )


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
    docs_url=(
        "/docs"
        if settings.ENABLE_DOCS
        else None
    ),
    redoc_url=(
        "/redoc"
        if settings.ENABLE_DOCS
        else None
    ),
    openapi_url=(
        "/openapi.json"
        if settings.ENABLE_DOCS
        else None
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=(
        settings.CORS_ALLOW_CREDENTIALS
    ),
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-Request-ID",
        "X-Process-Time",
        "Content-Disposition",
    ],
)

register_exception_handlers(
    app
)


@app.middleware("http")
async def request_context_middleware(
    request: Request,
    call_next,
):
    request_id = (
        request.headers.get(
            "X-Request-ID"
        )
        or uuid4().hex
    )

    request.state.request_id = (
        request_id
    )

    started_at = perf_counter()

    try:
        response = await call_next(
            request
        )

    except Exception:
        elapsed = (
            perf_counter()
            - started_at
        )

        logger.exception(
            "request_failed request_id=%s "
            "method=%s path=%s "
            "duration_ms=%.2f",
            request_id,
            request.method,
            request.url.path,
            elapsed * 1000,
        )

        raise

    elapsed = (
        perf_counter()
        - started_at
    )

    response.headers[
        "X-Request-ID"
    ] = request_id

    response.headers[
        "X-Process-Time"
    ] = f"{elapsed:.6f}"

    logger.info(
        "request_complete request_id=%s "
        "method=%s path=%s status=%s "
        "duration_ms=%.2f",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed * 1000,
    )

    return response


app.include_router(
    live_router
)

app.include_router(
    tokens_router
)

app.include_router(
    scanner_router
)

app.include_router(
    wallet_router
)

app.include_router(
    solana_router
)

app.include_router(
    helius_router
)

app.include_router(
    trades_router
)

app.include_router(
    discovered_wallets_router
)

app.include_router(
    paper_trading_router
)

app.include_router(
    paper_autopilot_router
)

app.include_router(
    live_trading_router
)
app.include_router(
    live_platform_router
)
app.include_router(
    live_operations_router
)


@app.get(
    "/",
    tags=["System"],
)
def home():
    return {
        "status": "online",
        "project":
            settings.APP_NAME,
        "version":
            settings.APP_VERSION,
        "environment":
            settings.ENVIRONMENT,
        "docs_enabled":
            settings.ENABLE_DOCS,
        "timestamp":
            utc_timestamp(),
    }


@app.get(
    "/health",
    tags=["System"],
)
def health():
    return {
        "status": "ok",
        "service":
            settings.APP_NAME,
        "version":
            settings.APP_VERSION,
        "timestamp":
            utc_timestamp(),
    }


@app.get(
    "/ready",
    tags=["System"],
    responses={
        503: {
            "description":
                "Servizio non pronto",
        },
    },
)
def readiness():
    try:
        with engine.connect() as connection:
            connection.execute(
                text("SELECT 1")
            )

    except SQLAlchemyError as exception:
        logger.warning(
            "readiness_check=failed "
            "dependency=database "
            "error_type=%s",
            type(exception).__name__,
        )

        return JSONResponse(
            status_code=503,
            content={
                "status":
                    "not_ready",
                "dependencies": {
                    "database":
                        "disconnected",
                    "helius":
                        "configured",
                    "solana_rpc":
                        "configured",
                },
                "timestamp":
                    utc_timestamp(),
            },
        )

    return {
        "status": "ready",
        "dependencies": {
            "database":
                "connected",
            "helius":
                "configured",
            "solana_rpc":
                "configured",
        },
        "timestamp":
            utc_timestamp(),
    }

# BEGIN M2 DIRECT RAW CAPTURE STATUS ENDPOINT
@app.get(
    "/integrity/raw-capture/status",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_raw_capture_status(
    db: Session = Depends(get_db),
):
    return get_raw_capture_status(db)
# END M2 DIRECT RAW CAPTURE STATUS ENDPOINT


# BEGIN M3 RAW CAPTURE GOVERNANCE ENDPOINTS
@app.get(
    "/integrity/raw-capture/readiness",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_raw_capture_readiness(
    db: Session = Depends(get_db),
):
    return get_raw_capture_readiness(db)


@app.post(
    "/integrity/raw-capture/canary",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def execute_raw_capture_canary(
    db: Session = Depends(get_db),
):
    return run_raw_capture_canary(db)


@app.get(
    "/integrity/raw-capture/retention/preview",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_raw_capture_retention_preview(
    provider: str | None = Query(
        default=None,
        min_length=1,
        max_length=64,
    ),
    batch_size: int | None = Query(
        default=None,
        ge=1,
        le=10_000,
    ),
    db: Session = Depends(get_db),
):
    try:
        return preview_raw_capture_retention(
            db,
            provider=provider,
            batch_size=batch_size,
        )
    except RawCaptureGovernanceError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={
                "code": exception.code,
                "message": str(exception),
            },
        ) from exception


@app.post(
    "/integrity/raw-capture/retention/prune",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def execute_raw_capture_retention_prune(
    request: RawCaptureRetentionPruneRequest,
    db: Session = Depends(get_db),
):
    try:
        return prune_raw_capture_retention(
            db,
            dry_run=request.dry_run,
            confirmation=request.confirmation,
            provider=request.provider,
            batch_size=request.batch_size,
        )
    except RawCaptureGovernanceError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={
                "code": exception.code,
                "message": str(exception),
            },
        ) from exception
# END M3 RAW CAPTURE GOVERNANCE ENDPOINTS

# BEGIN M4 VERSIONED PARSER REGISTRY AND CONTROLLED REPLAY
@app.get(
    "/integrity/parsers",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_blockchain_parser_registry():
    return get_parser_registry_status()


@app.get(
    "/integrity/replay/preview",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_normalization_replay_preview(
    parser_name: str = Query(min_length=3, max_length=80),
    parser_version: str = Query(min_length=5, max_length=64),
    selection_mode: str = Query(default="REPROCESS", max_length=16),
    provider: str | None = Query(default=None, min_length=1, max_length=64),
    event_type: str | None = Query(default=None, min_length=1, max_length=80),
    transaction_signature: str | None = Query(
        default=None,
        min_length=1,
        max_length=128,
    ),
    observed_wallet: str | None = Query(
        default=None,
        min_length=1,
        max_length=64,
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    try:
        return preview_normalization_replay(
            db,
            parser_name=parser_name,
            parser_version=parser_version,
            selection_mode=selection_mode,
            provider=provider,
            event_type=event_type,
            transaction_signature=transaction_signature,
            observed_wallet=observed_wallet,
            limit=limit,
        )
    except NormalizationReplayError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={
                "code": exception.code,
                "message": str(exception),
            },
        ) from exception


@app.post(
    "/integrity/replay/execute",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def execute_controlled_normalization_replay(
    request: NormalizationReplayExecuteRequest,
    db: Session = Depends(get_db),
):
    try:
        observed_from = (
            datetime.fromisoformat(request.observed_from)
            if request.observed_from
            else None
        )
        observed_to = (
            datetime.fromisoformat(request.observed_to)
            if request.observed_to
            else None
        )
        return execute_normalization_replay(
            db,
            parser_name=request.parser_name,
            parser_version=request.parser_version,
            selection_mode=request.selection_mode,
            confirmation=request.confirmation,
            provider=request.provider,
            event_type=request.event_type,
            transaction_signature=request.transaction_signature,
            observed_wallet=request.observed_wallet,
            observed_from=observed_from,
            observed_to=observed_to,
            limit=request.limit,
        )
    except ValueError as exception:
        if isinstance(exception, NormalizationReplayError):
            raise HTTPException(
                status_code=exception.status_code,
                detail={
                    "code": exception.code,
                    "message": str(exception),
                },
            ) from exception
        raise HTTPException(
            status_code=422,
            detail={
                "code": "REPLAY_DATETIME_INVALID",
                "message": "Intervallo temporale replay non valido.",
            },
        ) from exception


@app.get(
    "/integrity/replay/batches/{replay_id}",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_normalization_replay_batch(
    replay_id: str,
    db: Session = Depends(get_db),
):
    try:
        return get_normalization_replay_batch(db, replay_id)
    except NormalizationReplayError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={
                "code": exception.code,
                "message": str(exception),
            },
        ) from exception
# END M4 VERSIONED PARSER REGISTRY AND CONTROLLED REPLAY

# BEGIN M5 CANONICAL NORMALIZATION AND SHADOW VALIDATION
@app.get(
    "/integrity/canonical/status",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_canonical_shadow_status(
    db: Session = Depends(get_db),
):
    return get_canonical_shadow_status(db)


@app.get(
    "/integrity/canonical/materialization/preview",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_canonical_materialization_preview(
    provider: str | None = Query(default=None, min_length=1, max_length=64),
    observed_wallet: str | None = Query(
        default=None, min_length=1, max_length=64
    ),
    transaction_signature: str | None = Query(
        default=None, min_length=1, max_length=128
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    try:
        return preview_canonical_materialization(
            db,
            provider=provider,
            observed_wallet=observed_wallet,
            transaction_signature=transaction_signature,
            limit=limit,
        )
    except CanonicalShadowError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/canonical/materialization/execute",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def execute_canonical_materialization_endpoint(
    request: CanonicalMaterializationExecuteRequest,
    db: Session = Depends(get_db),
):
    try:
        return execute_canonical_materialization(
            db,
            confirmation=request.confirmation,
            provider=request.provider,
            observed_wallet=request.observed_wallet,
            transaction_signature=request.transaction_signature,
            limit=request.limit,
        )
    except CanonicalShadowError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/shadow-validation/preview",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_validation_preview(
    transaction_signature: str | None = Query(
        default=None, min_length=1, max_length=128
    ),
    observed_wallet: str | None = Query(
        default=None, min_length=1, max_length=64
    ),
    quality_status: str | None = Query(
        default=None, min_length=4, max_length=8
    ),
    limit: int = Query(default=200, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    try:
        return preview_shadow_validation(
            db,
            transaction_signature=transaction_signature,
            observed_wallet=observed_wallet,
            quality_status=quality_status,
            limit=limit,
        )
    except CanonicalShadowError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/shadow-validation/execute",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def execute_shadow_validation_endpoint(
    request: CanonicalShadowValidationExecuteRequest,
    db: Session = Depends(get_db),
):
    try:
        return execute_shadow_validation(
            db,
            confirmation=request.confirmation,
            transaction_signature=request.transaction_signature,
            observed_wallet=request.observed_wallet,
            quality_status=request.quality_status,
            limit=request.limit,
        )
    except CanonicalShadowError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/shadow-validation/batches/{validation_id}",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_validation_batch_endpoint(
    validation_id: str,
    db: Session = Depends(get_db),
):
    try:
        return get_shadow_validation_batch(db, validation_id)
    except CanonicalShadowError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception
# END M5 CANONICAL NORMALIZATION AND SHADOW VALIDATION

# BEGIN M6 CANONICAL QUALITY GATE
@app.get(
    "/integrity/quality-gate/status",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_canonical_quality_gate_status(
    db: Session = Depends(get_db),
):
    return get_canonical_quality_gate_status(db)


@app.get(
    "/integrity/quality-gate/preview",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_canonical_quality_gate_preview(
    validation_id: str | None = Query(
        default=None, min_length=36, max_length=36
    ),
    db: Session = Depends(get_db),
):
    try:
        return preview_canonical_quality_gate(
            db,
            validation_id=validation_id,
        )
    except CanonicalQualityGateError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/quality-gate/assess",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def execute_canonical_quality_assessment_endpoint(
    request: CanonicalQualityAssessmentRequest,
    db: Session = Depends(get_db),
):
    try:
        return execute_canonical_quality_assessment(
            db,
            confirmation=request.confirmation,
            validation_id=request.validation_id,
        )
    except CanonicalQualityGateError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/quality-gate/assessments/{assessment_id}",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_canonical_quality_assessment_endpoint(
    assessment_id: str,
    db: Session = Depends(get_db),
):
    try:
        return get_canonical_quality_assessment(db, assessment_id)
    except CanonicalQualityGateError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception
# END M6 CANONICAL QUALITY GATE

# BEGIN M7 CANONICAL PARSER PROMOTION LEDGER
@app.get(
    "/integrity/parser-promotion/status",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_parser_promotion_status(
    db: Session = Depends(get_db),
):
    return get_parser_promotion_status(db)


@app.get(
    "/integrity/parser-promotion/preview",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_parser_promotion_preview(
    assessment_id: str | None = Query(
        default=None, min_length=36, max_length=36
    ),
    scope: str = Query(default="SHADOW_ONLY", max_length=32),
    db: Session = Depends(get_db),
):
    try:
        return preview_parser_promotion(
            db,
            assessment_id=assessment_id,
            scope=scope,
        )
    except CanonicalParserPromotionError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/parser-promotion/approve",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def approve_parser_promotion_endpoint(
    request: CanonicalParserPromotionApproveRequest,
    db: Session = Depends(get_db),
):
    try:
        return approve_parser_promotion(
            db,
            confirmation=request.confirmation,
            assessment_id=request.assessment_id,
            scope=request.scope,
            actor_label=request.actor_label,
            note=request.note,
        )
    except CanonicalParserPromotionError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/parser-promotion/revoke",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def revoke_parser_promotion_endpoint(
    request: CanonicalParserPromotionRevokeRequest,
    db: Session = Depends(get_db),
):
    try:
        return revoke_parser_promotion(
            db,
            promotion_id=request.promotion_id,
            confirmation=request.confirmation,
            reason=request.reason,
            actor_label=request.actor_label,
        )
    except CanonicalParserPromotionError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/parser-promotion/promotions/{promotion_id}",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_parser_promotion_endpoint(
    promotion_id: str,
    db: Session = Depends(get_db),
):
    try:
        return get_parser_promotion(db, promotion_id)
    except CanonicalParserPromotionError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception
# END M7 CANONICAL PARSER PROMOTION LEDGER
